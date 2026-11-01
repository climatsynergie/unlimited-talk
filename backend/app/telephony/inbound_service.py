"""Inbound settings and manual CRM follow-up; no provider commands or media claims."""
from datetime import datetime, timezone
import json
import re
from uuid import uuid4, UUID
from fastapi import HTTPException
from app.identity.service import query, audit
from app.campaigns.service import fingerprint
from app.telephony.twilio_voice import sid

STAGES = [('pending', 'À traiter'), ('claimed', 'Pris en charge'), ('callback', 'Rappel programmé'), ('handled', 'Traité')]
FOLLOWUP_SELECT = '''SELECT f.*,c.profile,coalesce(c.do_not_contact,false) AS do_not_contact,
    coalesce(c.non_interested,false) AS non_interested,u.display_name AS owner_name,
    (SELECT count(*) FROM staging.inbound_interactions i WHERE i.followup_id=f.id) AS call_count
    FROM staging.inbound_followups f LEFT JOIN staging.contacts c ON c.phone=f.caller_number
    LEFT JOIN staging.identity_users u ON u.id=f.owner_id'''


def queue(db, actor, identifier, *, lock=False):
    row = query(db, 'SELECT * FROM staging.inbound_queues WHERE id=:id'+(' FOR UPDATE' if lock else ''), id=identifier).mappings().first()
    if not row: raise HTTPException(404, 'File de réception introuvable.')
    if actor['role'] != 'admin' and not query(db, '''SELECT 1 FROM staging.inbound_queue_agents
            WHERE queue_id=:id AND user_id=:user AND is_active''', id=identifier, user=actor['id']).first():
        raise HTTPException(403, 'Cette file de réception ne vous est pas attribuée.')
    return dict(row)


def queue_detail(db, actor, identifier):
    result = queue(db, actor, identifier)
    result['agents'] = [dict(r) for r in query(db, '''SELECT a.user_id,a.mode,u.display_name,u.is_active AS account_active
        FROM staging.inbound_queue_agents a JOIN staging.identity_users u ON u.id=a.user_id
        WHERE a.queue_id=:id AND a.is_active ORDER BY lower(u.display_name),u.id''', id=identifier).mappings()]
    # No provider route is installed by this milestone. Do not imply that a
    # configuration save makes this number ring in the browser.
    result['routing_active'] = False
    return result


def replay(db, table, actor, request_id, identifier, digest, key):
    # All identifiers here are fixed service constants, never browser values.
    old = query(db, 'SELECT * FROM staging.'+table+' WHERE request_id=:id', id=request_id).mappings().first()
    if old:
        if old['actor_id'] != actor['id'] or old[key] != identifier or old['request_hash'] != digest:
            raise HTTPException(409, 'Cet identifiant d’action a déjà été utilisé autrement.')
        return old['details']['result']
    return None


def settings(db, actor, identifier, body, request_id, version=None):
    values = body.model_dump(mode='json', exclude={'id', 'request_id', 'version'})
    digest = fingerprint({'settings': values, 'version': version})
    previous = replay(db, 'inbound_queue_events', actor, request_id, identifier, digest, 'queue_id')
    if previous is not None: return previous
    # Lock referenced users BEFORE the queue. An agent may hold their identity
    # lock while handling a follow-up; a later FK check must not invert that order.
    members = [str(a.user_id) for a in body.agents]
    valid = query(db, '''SELECT id,is_active FROM staging.identity_users
        WHERE id=ANY(CAST(:ids AS uuid[])) ORDER BY id FOR KEY SHARE''', ids=members).mappings().all()
    if len(valid) != len(members) or any(not r['is_active'] for r in valid):
        raise HTTPException(409, 'Choisissez uniquement des comptes actifs et actualisez la liste des agents.')
    if version is None:
        query(db, 'SELECT pg_advisory_xact_lock(74192009)')
        old = replay(db, 'inbound_queue_events', actor, request_id, identifier, digest, 'queue_id')
        if old is not None: return old
        if query(db, 'SELECT count(*) FROM staging.inbound_queues').scalar_one() >= 200:
            raise HTTPException(409, 'La limite de 200 files est atteinte.')
        query(db, '''INSERT INTO staging.inbound_queues(id,name,phone,timezone,hours,max_wait_seconds,offer_seconds,is_active,created_by)
            VALUES (:id,:name,:phone,:timezone,CAST(:hours AS jsonb),:max_wait_seconds,:offer_seconds,:is_active,:actor)''',
            id=identifier, actor=actor['id'], **{k:v for k,v in values.items() if k not in {'agents','hours'}}, hours=json.dumps(values['hours']))
        action, saved_version = 'queue.created', 0
    else:
        current = queue(db, actor, identifier, lock=True)
        old = replay(db, 'inbound_queue_events', actor, request_id, identifier, digest, 'queue_id')
        if old is not None: return old
        if current['version'] != version:
            raise HTTPException(409, 'Cette file a changé. Actualisez ses réglages avant de les enregistrer.')
        if query(db, '''SELECT 1 FROM staging.inbound_followups WHERE queue_id=:id AND stage<>'handled'
            AND owner_id IS NOT NULL AND NOT(owner_id=ANY(CAST(:ids AS uuid[]))) LIMIT 1''', id=identifier, ids=members).first():
            raise HTTPException(409, 'Réattribuez les suivis en cours avant de retirer leur agent de cette file.')
        if current['phone'] != values['phone'] and query(db, 'SELECT 1 FROM staging.inbound_interactions WHERE queue_id=:id LIMIT 1', id=identifier).first():
            raise HTTPException(409, 'Cette file possède un historique. Créez une autre file pour un autre numéro.')
        query(db, '''UPDATE staging.inbound_queues SET name=:name,phone=:phone,timezone=:timezone,hours=CAST(:hours AS jsonb),
            max_wait_seconds=:max_wait_seconds,offer_seconds=:offer_seconds,is_active=:is_active,version=version+1,
            updated_at=clock_timestamp() WHERE id=:id''', id=identifier,
            **{k:v for k,v in values.items() if k not in {'agents','hours'}}, hours=json.dumps(values['hours']))
        action, saved_version = 'queue.updated', version+1
    query(db, 'UPDATE staging.inbound_queue_agents SET is_active=false WHERE queue_id=:id', id=identifier)
    for member in body.agents:
        query(db, '''INSERT INTO staging.inbound_queue_agents(queue_id,user_id,mode,assigned_by)
            VALUES (:queue,:user,:mode,:actor) ON CONFLICT(queue_id,user_id) DO UPDATE SET mode=excluded.mode,
            is_active=true,assigned_by=excluded.assigned_by,assigned_at=clock_timestamp()''',
            queue=identifier, user=member.user_id, mode=member.mode, actor=actor['id'])
    result = {'id': str(identifier), 'version': saved_version}
    query(db, '''INSERT INTO staging.inbound_queue_events(queue_id,actor_id,request_id,request_hash,action,details)
        VALUES (:queue,:actor,:request,:hash,:action,CAST(:details AS jsonb))''', queue=identifier, actor=actor['id'],
        request=request_id, hash=digest, action=action, details=json.dumps({'settings':values,'result':result}))
    audit(db, actor['id'], action, identifier)
    return result


def followup(db, actor, identifier, *, lock=False):
    found = query(db, 'SELECT queue_id FROM staging.inbound_followups WHERE id=:id', id=identifier).scalar_one_or_none()
    if found is None: raise HTTPException(404, 'Suivi introuvable.')
    queue(db, actor, found, lock=lock)
    if lock: query(db, 'SELECT id FROM staging.inbound_followups WHERE id=:id FOR UPDATE', id=identifier)
    return dict(query(db, FOLLOWUP_SELECT+' WHERE f.id=:id', id=identifier).mappings().one())


def record_event(db, identifier, action, details, *, actor=None, request_id=None, digest=None):
    query(db, '''INSERT INTO staging.inbound_followup_events(followup_id,actor_id,request_id,request_hash,action,details)
        VALUES (:id,:actor,:request,:hash,:action,CAST(:details AS jsonb))''', id=identifier, actor=actor,
        request=request_id, hash=digest, action=action, details=json.dumps(details))


def record_missed(db, *, queue_id, account_sid, call_sid, caller_number, called_number, outcome, received_at, ended_at):
    """Trusted adapter boundary for a VERIFIED terminal unanswered call only.

    No HTTP route exposes this function. Future authenticated routing/recovery
    must establish ownership and the final provider outcome before invoking it.
    Queue changes and a provider event commit in the caller's SAME transaction.
    """
    if (not isinstance(queue_id, UUID) or not sid(account_sid, 'AC')
            or not sid(call_sid, 'CA')
            or outcome not in {'missed','abandoned','outside_hours','overflowed'}
            or not isinstance(called_number, str) or not re.fullmatch(r'\+[1-9][0-9]{8,14}', called_number)
            or (caller_number is not None and (not isinstance(caller_number, str) or not re.fullmatch(r'\+[1-9][0-9]{8,14}', caller_number)))):
        raise ValueError('Interaction entrante invalide')
    for instant in (received_at, ended_at):
        if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError('Instant avec fuseau requis')
    if ended_at < received_at: raise ValueError('Chronologie invalide')
    digest = fingerprint(dict(queue=str(queue_id), caller=caller_number, called=called_number, outcome=outcome,
        received=received_at.astimezone(timezone.utc).isoformat(), ended=ended_at.astimezone(timezone.utc).isoformat()))
    # Serialize a provider CallSid even if a faulty adapter sends a different
    # queue; then queue locking also serializes grouping against CRM closure.
    lock_key = int.from_bytes(bytes.fromhex(fingerprint([account_sid,call_sid]))[:8], 'big', signed=True)
    query(db, 'SELECT pg_advisory_xact_lock(:key)', key=lock_key)
    old = query(db, 'SELECT * FROM staging.inbound_interactions WHERE account_sid=:account AND call_sid=:call', account=account_sid, call=call_sid).mappings().first()
    if old:
        if old['fingerprint'] != digest: raise ValueError('Interaction déjà enregistrée avec un autre résultat')
        return old['followup_id']
    contact = query(db, 'SELECT id FROM staging.contacts WHERE phone=:phone FOR KEY SHARE', phone=caller_number).scalar_one_or_none() if caller_number else None
    configured = query(db, 'SELECT * FROM staging.inbound_queues WHERE id=:id FOR UPDATE', id=queue_id).mappings().first()
    if not configured or configured['phone'] != called_number: raise ValueError('Numéro sans file associée')
    existing = query(db, '''SELECT id FROM staging.inbound_followups WHERE queue_id=:queue AND caller_number=:phone
        AND stage<>'handled' FOR UPDATE''', queue=queue_id, phone=caller_number).scalar_one_or_none() if caller_number else None
    identifier = existing or uuid4()
    if existing is None:
        query(db, '''INSERT INTO staging.inbound_followups(id,queue_id,contact_id,caller_number)
            VALUES (:id,:queue,:contact,:phone)''', id=identifier, queue=queue_id, contact=contact, phone=caller_number)
    else:
        query(db, 'UPDATE staging.inbound_followups SET contact_id=coalesce(contact_id,:contact),version=version+1,updated_at=clock_timestamp() WHERE id=:id', id=identifier,contact=contact)
    interaction_id = uuid4()
    query(db, '''INSERT INTO staging.inbound_interactions(id,queue_id,followup_id,account_sid,call_sid,caller_number,called_number,outcome,received_at,ended_at,fingerprint)
        VALUES (:id,:queue,:followup,:account,:call,:caller,:called,:outcome,:received,:ended,:hash)''', id=interaction_id,
        queue=queue_id, followup=identifier, account=account_sid, call=call_sid, caller=caller_number,
        called=called_number, outcome=outcome, received=received_at, ended=ended_at, hash=digest)
    record_event(db, identifier, 'call.received', {'interaction_id':str(interaction_id),'outcome':outcome})
    return identifier


def change_followup(db, actor, identifier, body, due=None):
    followup(db, actor, identifier)
    digest = fingerprint(body.model_dump(mode='json'))
    previous = replay(db, 'inbound_followup_events', actor, body.request_id, identifier, digest, 'followup_id')
    if previous is not None: return previous
    target = body.owner_id or (actor['id'] if body.stage!='pending' else None)
    # Same identity-before-queue order as settings; no FK lock acquired late.
    if target:
        active = query(db, 'SELECT is_active FROM staging.identity_users WHERE id=:id FOR KEY SHARE', id=target).scalar_one_or_none()
        if not active: raise HTTPException(409, 'Choisissez un agent actif.')
    if body.stage=='callback':
        phone = query(db,'SELECT caller_number FROM staging.inbound_followups WHERE id=:id',id=identifier).scalar_one_or_none()
        if phone: query(db,'SELECT id FROM staging.contacts WHERE phone=:phone FOR UPDATE',phone=phone)
    current = followup(db, actor, identifier, lock=True)
    digest = fingerprint(body.model_dump(mode='json'))
    old = replay(db, 'inbound_followup_events', actor, body.request_id, identifier, digest, 'followup_id')
    if old is not None: return old
    if current['version'] != body.version: raise HTTPException(409, 'Ce suivi a changé. Actualisez sa fiche avant de le modifier.')
    if current['stage']=='handled': raise HTTPException(409, 'Ce suivi est clôturé. Son historique est conservé.')
    if actor['role']!='admin' and (current['owner_id'] not in (None,actor['id']) or target not in (None,actor['id'])):
        raise HTTPException(403, 'Ce suivi est pris en charge par un autre agent.')
    if target and not query(db, '''SELECT 1 FROM staging.inbound_queue_agents WHERE queue_id=:queue
            AND user_id=:user AND is_active''', queue=current['queue_id'], user=target).first():
        raise HTTPException(409, 'Attribuez cet agent à la file avant de lui confier le suivi.')
    if body.stage=='callback':
        if not current['caller_number']: raise HTTPException(409, 'Le numéro de cet appelant est masqué. Aucun rappel ne peut être programmé.')
        if current['do_not_contact'] or current['non_interested']:
            raise HTTPException(409, 'Ce contact est bloqué. Un administrateur doit lever sa restriction avant un rappel.')
        if due is None or due <= datetime.now(timezone.utc): raise HTTPException(422, 'Choisissez une date et une heure futures.')
    result = {'id':str(identifier), 'version':current['version']+1}
    query(db, '''UPDATE staging.inbound_followups SET stage=:stage,owner_id=:owner,callback_at=:due,callback_timezone=:zone,
        closed_at=CASE WHEN :stage='handled' THEN clock_timestamp() ELSE NULL END,
        version=version+1,updated_at=clock_timestamp() WHERE id=:id''', id=identifier, stage=body.stage,
        owner=target, due=due, zone=body.timezone if due else None)
    record_event(db, identifier, 'followup.updated', {'before':{'stage':current['stage'],'owner_id':str(current['owner_id']) if current['owner_id'] else None},
        'after':{'stage':body.stage,'owner_id':str(target) if target else None,'callback_at':due.isoformat() if due else None,'timezone':body.timezone if due else None},
        'result':result}, actor=actor['id'], request_id=body.request_id, digest=digest)
    audit(db, actor['id'], 'inbound.followup_updated', identifier)
    return result

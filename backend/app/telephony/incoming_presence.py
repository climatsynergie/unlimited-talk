"""Authenticated, leased browser registrations; media claims are not call endings."""
from uuid import uuid4
from fastapi import HTTPException
from app.identity.service import query,audit
from app.telephony.incoming_schema import installed
from app.telephony.twilio_voice import incoming_token,ManualVoiceProfile


ACTIVE="('offered','accepted','connected')"


def routing_states(db,profile):
    if not isinstance(profile,ManualVoiceProfile) or not installed(db):return {}
    return {row['queue_id']:row['route_state'] for row in query(db,'''SELECT l.queue_id,l.route_state
        FROM staging.inbound_lines l JOIN staging.inbound_queues q ON q.id=l.queue_id AND q.phone=l.phone
        WHERE l.account_sid=:account AND l.public_origin=:origin''',account=profile.account_sid,origin=profile.public_origin).mappings()}


def queues(db,actor,profile):
    return query(db,'''SELECT q.id,q.name,q.phone FROM staging.inbound_queues q
        JOIN staging.inbound_queue_agents a ON a.queue_id=q.id AND a.user_id=:actor AND a.is_active
        JOIN staging.inbound_lines l ON l.queue_id=q.id AND l.phone=q.phone AND l.account_sid=:account
        WHERE q.is_active AND l.route_state='active' AND l.public_origin=:origin
        ORDER BY lower(q.name),q.id''',actor=actor['id'],account=profile.account_sid,origin=profile.public_origin).mappings().all()


def active_offer(db,actor):
    row=query(db,'''SELECT o.id AS offer_id,o.call_id,o.state,o.registration_id,o.session_hash,
        c.caller_number,c.called_number,c.connected_at,c.state AS call_state,q.name AS queue_name
        FROM staging.inbound_offers o JOIN staging.inbound_calls c ON c.id=o.call_id
        JOIN staging.inbound_queues q ON q.id=c.queue_id WHERE o.actor_id=:actor AND o.state<>'finished'
        ORDER BY o.offered_at DESC LIMIT 1''',actor=actor['id']).mappings().first()
    if row is None:return None
    return {key:value for key,value in row.items() if key!='session_hash'}|{'owned_session':row['session_hash']==actor['session_hash']}


def session(db,actor,profile,enabled):
    if not installed(db) or not isinstance(profile,ManualVoiceProfile):
        return {'enabled':False,'queues':[],'registration':None,'active':None}
    memberships=queues(db,actor,profile)
    registration=query(db,'''SELECT id,browser_id,available,media_ready,lease_until>clock_timestamp() AS alive,
        session_hash FROM staging.inbound_registrations WHERE actor_id=:actor AND closed_at IS NULL''',actor=actor['id']).mappings().first()
    return {'enabled':bool(enabled and memberships),'queues':[dict(row) for row in memberships],
        'registration':({key:value for key,value in registration.items() if key!='session_hash'}|
            {'owned_session':registration['session_hash']==actor['session_hash']}) if registration else None,
        'active':active_offer(db,actor)}


def register(db,actor,profile,browser_id):
    if not installed(db) or not isinstance(profile,ManualVoiceProfile) or not queues(db,actor,profile):
        raise HTTPException(409,'Aucune ligne connectée ne vous est attribuée pour recevoir des appels.')
    row=query(db,'''SELECT *,lease_until>clock_timestamp() AS alive FROM staging.inbound_registrations
        WHERE actor_id=:actor AND closed_at IS NULL FOR UPDATE''',actor=actor['id']).mappings().first()
    if row and (row['session_hash']!=actor['session_hash'] or row['browser_id']!=browser_id):
        if (row['alive'] and row['available'] and row['media_ready']) or active_offer(db,actor):
            raise HTTPException(409,'Votre réception est déjà ouverte dans une autre fenêtre. Mettez-la en pause dans cette fenêtre avant de la reprendre ici.')
        query(db,'UPDATE staging.inbound_registrations SET closed_at=clock_timestamp(),available=false,media_ready=false WHERE id=:id',id=row['id'])
        row=None
    if row is None:
        identifier=uuid4()
        query(db,'''INSERT INTO staging.inbound_registrations(id,actor_id,session_hash,browser_id,lease_until)
            VALUES (:id,:actor,:session,:browser,clock_timestamp()+interval '30 seconds')''',id=identifier,actor=actor['id'],session=actor['session_hash'],browser=browser_id)
        audit(db,actor['id'],'inbound.registration_created',identifier)
    else:
        identifier=row['id']
        query(db,'''UPDATE staging.inbound_registrations SET last_seen_at=clock_timestamp(),
            lease_until=clock_timestamp()+interval '30 seconds' WHERE id=:id''',id=identifier)
    return {'id':identifier,'token':incoming_token(profile,identifier),'expires_in':300}


def own_registration(db,actor,identifier,*,lock=False):
    row=query(db,'SELECT * FROM staging.inbound_registrations WHERE id=:id'+(' FOR UPDATE' if lock else ''),id=identifier).mappings().first()
    if not row or row['closed_at'] or row['actor_id']!=actor['id'] or row['session_hash']!=actor['session_hash']:
        raise HTTPException(404,'Session de réception introuvable.')
    return row


def heartbeat(db,actor,profile,identifier,available,media_ready):
    row=own_registration(db,actor,identifier,lock=True)
    available=bool(available and queues(db,actor,profile))
    query(db,'''UPDATE staging.inbound_registrations SET available=:available,media_ready=:ready,
        ready_since=CASE WHEN :available AND :ready AND NOT(available AND media_ready)
            THEN clock_timestamp() ELSE ready_since END,
        last_seen_at=clock_timestamp(),lease_until=clock_timestamp()+interval '30 seconds' WHERE id=:id''',
        id=identifier,available=available,ready=bool(media_ready))
    if available!=row['available']:audit(db,actor['id'],'inbound.ready' if available else 'inbound.pause',identifier)
    return {'available':available,'media_ready':bool(media_ready),'active':active_offer(db,actor)}


def offer(db,actor,identifier):
    row=query(db,'''SELECT o.*,c.caller_number,c.called_number,c.state AS call_state,c.queue_id,
        c.parent_call_sid,q.name AS queue_name FROM staging.inbound_offers o
        JOIN staging.inbound_calls c ON c.id=o.call_id JOIN staging.inbound_queues q ON q.id=c.queue_id WHERE o.id=:id''',id=identifier).mappings().first()
    if not row or row['actor_id']!=actor['id'] or row['session_hash']!=actor['session_hash']:
        raise HTTPException(404,'Proposition d’appel introuvable.')
    return row


def public_offer(row):
    return {key:row[key] for key in ('id','call_id','registration_id','caller_number','called_number','queue_name','state','call_state')}


def choose(db,actor,identifier,registration_id,accept):
    # The signed answer hook, not a browser-supplied CallSid, authorizes media.
    own_registration(db,actor,registration_id)
    original=offer(db,actor,identifier)
    query(db,'SELECT id FROM staging.inbound_calls WHERE id=:id FOR UPDATE',id=original['call_id'])
    row=query(db,'SELECT * FROM staging.inbound_offers WHERE id=:id FOR UPDATE',id=identifier).mappings().one()
    if row['registration_id']!=registration_id or row['state']=='finished' or row['terminal_at'] is not None:
        raise HTTPException(409,'Cette proposition d’appel n’est plus disponible.')
    if accept:
        if original['call_state'] not in {'offered','connected'} or row['reject_requested_at']:
            raise HTTPException(409,'Cette proposition d’appel n’est plus disponible.')
        query(db,"UPDATE staging.inbound_offers SET accepted_at=coalesce(accepted_at,clock_timestamp()),state=CASE WHEN state='offered' THEN 'accepted' ELSE state END WHERE id=:id",id=identifier)
        audit(db,actor['id'],'inbound.accept_requested',identifier)
    elif row['state']!='connected':
        query(db,'UPDATE staging.inbound_offers SET reject_requested_at=coalesce(reject_requested_at,clock_timestamp()) WHERE id=:id',id=identifier)
    return public_offer(offer(db,actor,identifier))

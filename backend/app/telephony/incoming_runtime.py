"""One durable incoming offer at a time, sharing outbound actor/account admission."""
from datetime import timedelta
from uuid import uuid4
import re
from fastapi import HTTPException
from app.identity.service import query
from app.identity.security import IDLE_SECONDS
from app.telephony import service
from app.telephony.inbound_settings import within_hours
from app.telephony.twilio_voice import incoming_identity

VM_SECONDS=120
LEASE_SECONDS=30


def event(db,call_id,kind,details):
    import json
    query(db,'''INSERT INTO staging.inbound_call_events(call_id,kind,fingerprint,details)
        VALUES (:id,:kind,:hash,CAST(:details AS jsonb)) ON CONFLICT DO NOTHING''',
        id=call_id,kind=kind,hash=service.fingerprint(details),details=json.dumps(details))


def lock_account(db,profile):
    query(db,'SELECT pg_advisory_xact_lock(hashtextextended(:account,74192010))',account=profile.account_sid)


def parent(db,profile,identifier,params,*,lock=False):
    row=query(db,'SELECT * FROM staging.inbound_calls WHERE id=:id'+(' FOR UPDATE' if lock else ''),id=identifier).mappings().first()
    if not row or row['account_sid']!=profile.account_sid or params['CallSid']!=row['parent_call_sid']:
        raise HTTPException(403,'Notification sans appel entrant associé.')
    return row


def receive(db,profile,params,*,verified_voice=True):
    called=params.get('To','');raw=params.get('From','')
    if (not re.fullmatch(r'\+[1-9][0-9]{8,14}',called) or not raw
            or params.get('Direction','inbound')!='inbound'):
        raise HTTPException(403,'Ligne de réception non reconnue.')
    line=query(db,'''SELECT l.* FROM staging.inbound_lines l JOIN staging.inbound_queues q ON q.id=l.queue_id
        WHERE l.account_sid=:account AND l.phone=:phone AND q.phone=l.phone AND l.public_origin=:origin
        AND l.route_state IN ('connecting','active')''',account=profile.account_sid,phone=called,origin=profile.public_origin).mappings().first()
    if line is None:raise HTTPException(403,'Ligne de réception non connectée.')
    binding=service.fingerprint(dict(account=profile.account_sid,parent=params['CallSid'],caller=raw,called=called))
    lock_account(db,profile)
    row=query(db,'SELECT * FROM staging.inbound_calls WHERE account_sid=:account AND parent_call_sid=:sid FOR UPDATE',account=profile.account_sid,sid=params['CallSid']).mappings().first()
    if row:
        if row['caller_fingerprint']!=binding:raise HTTPException(403,'Appel entrant incohérent.')
        return dict(row)
    identifier=uuid4()
    row=query(db,'''INSERT INTO staging.inbound_calls(id,queue_id,account_sid,parent_call_sid,caller_number,called_number,caller_fingerprint)
        VALUES (:id,:queue,:account,:sid,:caller,:called,:hash) RETURNING *''',id=identifier,queue=line['queue_id'],account=profile.account_sid,
        sid=params['CallSid'],caller=raw if re.fullmatch(r'\+[1-9][0-9]{8,14}',raw) else None,called=called,hash=binding).mappings().one()
    if verified_voice:
        query(db,"UPDATE staging.inbound_lines SET route_state='active',verified_at=clock_timestamp(),last_error=NULL WHERE queue_id=:id",id=line['queue_id'])
    event(db,identifier,'received',{})
    return dict(row)


ELIGIBLE='''FROM staging.identity_users u JOIN staging.inbound_registrations r ON r.actor_id=u.id
 JOIN staging.inbound_queue_agents a ON a.user_id=u.id AND a.queue_id=:queue AND a.is_active
 JOIN staging.identity_sessions s ON s.token_hash=r.session_hash AND s.user_id=u.id
 LEFT JOIN staging.voice_dialer_sessions d ON d.actor_id=u.id
 LEFT JOIN LATERAL(SELECT v.finished_at FROM staging.voice_intents v WHERE v.actor_id=u.id AND v.consumed_at IS NOT NULL
    ORDER BY v.created_at DESC,v.id DESC LIMIT 1) last_out ON true
 LEFT JOIN LATERAL(SELECT o.ended_at FROM staging.inbound_offers o WHERE o.actor_id=u.id AND o.connected_at IS NOT NULL
    ORDER BY o.offered_at DESC,o.id DESC LIMIT 1) last_in ON true
 WHERE u.is_active AND (u.role<>'admin' OR u.mfa_secret IS NOT NULL)
 AND r.closed_at IS NULL AND r.available AND r.media_ready AND r.lease_until>clock_timestamp()
 AND s.mfa_verified AND s.expires_at>clock_timestamp()
 AND s.last_seen_at>clock_timestamp()-make_interval(secs=>:idle)
 AND NOT coalesce(d.mode='booking' AND d.lease_until>clock_timestamp(),false)
 AND (last_out.finished_at IS NULL OR last_out.finished_at<=clock_timestamp()-interval '10 seconds')
 AND (last_in.ended_at IS NULL OR last_in.ended_at<=clock_timestamp()-interval '10 seconds')
 AND NOT EXISTS(SELECT 1 FROM staging.voice_intents v WHERE v.actor_id=u.id
    AND v.state IN ('reserved','authorized','ringing','answered') AND (v.state<>'reserved' OR v.expires_at>clock_timestamp()))
 AND NOT EXISTS(SELECT 1 FROM staging.inbound_offers o WHERE o.actor_id=u.id AND o.state<>'finished')
 AND NOT EXISTS(SELECT 1 FROM staging.inbound_offers o WHERE o.call_id=:call AND o.actor_id=u.id)
'''


def step(db,profile,identifier,params,*,enabled):
    row=parent(db,profile,identifier,params)
    now=query(db,'SELECT clock_timestamp()').scalar_one()
    configured=query(db,'SELECT * FROM staging.inbound_queues WHERE id=:id',id=row['queue_id']).mappings().one()
    line=query(db,'''SELECT 1 FROM staging.inbound_lines WHERE queue_id=:id AND account_sid=:account
        AND phone=:phone AND public_origin=:origin AND route_state IN ('connecting','active')''',
        id=row['queue_id'],account=profile.account_sid,phone=row['called_number'],origin=profile.public_origin).first()
    enabled=bool(enabled and line)
    def waiting(value=row):return {'action':'wait','call':dict(value)}
    if row['state']=='finished':return {'action':'hangup','call':dict(row)}
    if row['state']=='connected':
        current=query(db,'SELECT terminal_at FROM staging.inbound_offers WHERE id=:id',id=row['current_offer_id']).mappings().first()
        return {'action':'hangup' if current and current['terminal_at'] else 'wait','call':dict(row)}
    in_hours=not configured['hours'] or within_hours(configured['hours'],configured['timezone'],now)
    expired=now>=row['received_at']+timedelta(seconds=configured['max_wait_seconds'])
    if row['state']=='voicemail' or not configured['is_active'] or not in_hours or expired or not enabled:
        row=parent(db,profile,identifier,params,lock=True)
        if row['state']=='finished':return {'action':'hangup','call':dict(row)}
        if row['state']=='connected':return waiting(row)
        # The record instruction, like an offer, is emitted at most once.
        if row['voicemail_emitted_at']:
            deadline=row['voicemail_emitted_at']+timedelta(seconds=VM_SECONDS+15)
            return {'action':'hangup' if now>=deadline else 'wait','call':dict(row)}
        cause='outside_hours' if not in_hours else 'overflowed' if expired else 'missed'
        row=query(db,'''UPDATE staging.inbound_calls SET state='voicemail',outcome=:cause,
            voicemail_emitted_at=clock_timestamp() WHERE id=:id RETURNING *''',id=identifier,cause=cause).mappings().one()
        event(db,identifier,'voicemail.started',{'reason':cause})
        return {'action':'voicemail','call':dict(row)}
    if row['state']=='offered':return waiting()
    values=dict(queue=row['queue_id'],call=identifier,idle=IDLE_SECONDS)
    # Never wait on a busy agent, and never acquire an actor lock after account
    # admission. Outbound authentication takes that actor lock first as well.
    candidate=query(db,'''SELECT u.id,r.id AS registration_id,r.session_hash
        '''+ELIGIBLE+''' ORDER BY greatest(r.ready_since,coalesce(last_out.finished_at,r.ready_since),
            coalesce(last_in.ended_at,r.ready_since)),u.id FOR UPDATE OF u SKIP LOCKED LIMIT 1''',**values).mappings().first()
    if not candidate:return waiting()
    lock_account(db,profile)
    row=parent(db,profile,identifier,params,lock=True)
    if row['state']!='waiting':return {'action':'hangup' if row['state']=='finished' else 'wait','call':dict(row)}
    # Recheck after locking, on a fresh statement snapshot: an outbound
    # reservation could have committed between candidate lookup and actor lock.
    if not query(db,'SELECT u.id '+ELIGIBLE+' AND u.id=:actor',**values,actor=candidate['id']).first():return waiting(row)
    live=query(db,'''SELECT (SELECT count(*) FROM staging.voice_intents WHERE account_sid=:account
        AND state IN ('reserved','authorized','ringing','answered') AND (state<>'reserved' OR expires_at>clock_timestamp()))
        +(SELECT count(*) FROM staging.inbound_offers o JOIN staging.inbound_calls c ON c.id=o.call_id
        WHERE c.account_sid=:account AND o.state<>'finished')''',account=profile.account_sid).scalar_one()
    if live>=profile.max_concurrent_calls:return waiting(row)
    fresh=query(db,'SELECT * FROM staging.inbound_queues WHERE id=:id',id=row['queue_id']).mappings().one()
    now=query(db,'SELECT clock_timestamp()').scalar_one()
    remaining=int((row['received_at']+timedelta(seconds=fresh['max_wait_seconds'])-now).total_seconds())
    if remaining<1 or not fresh['is_active'] or (fresh['hours'] and not within_hours(fresh['hours'],fresh['timezone'],now)):
        return waiting(row)
    offer=uuid4()
    selected=query(db,'''INSERT INTO staging.inbound_offers(id,call_id,actor_id,registration_id,session_hash,client_identity)
        VALUES (:id,:call,:actor,:registration,:session,:identity) RETURNING *''',id=offer,call=identifier,actor=candidate['id'],
        registration=candidate['registration_id'],session=candidate['session_hash'],identity=incoming_identity(candidate['registration_id'])).mappings().one()
    query(db,"UPDATE staging.inbound_calls SET state='offered',current_offer_id=:offer WHERE id=:id",id=identifier,offer=offer)
    event(db,identifier,'agent.offered',{'offer_id':str(offer),'actor_id':str(candidate['id'])})
    return {'action':'offer','call':dict(row),'offer':dict(selected),'seconds':max(1,min(fresh['offer_seconds'],remaining))}

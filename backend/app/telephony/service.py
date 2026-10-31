"""PostgreSQL owns authorization, one-time consumption and provider history.

This controlled path never selects imported contacts or calls the REST Calls API.
Only the first authenticated Voice webhook can receive Dial instructions. Lost
responses remain authorized/uncertain until a terminal provider event; no timer
silently reuses a consumed reservation.
"""
import hashlib
import json
import re
from uuid import UUID

from fastapi import HTTPException
from app.identity.service import query, audit
from app.telephony.twilio_voice import client_identity, sid

ACTIVE = {'reserved', 'authorized', 'ringing', 'answered'}
TERMINAL = {'finished', 'cancelled', 'expired'}
OUTCOMES = {'completed', 'busy', 'no-answer', 'failed', 'canceled'}
PROGRESS = {'queued': 'authorized', 'initiated': 'authorized', 'ringing': 'ringing', 'in-progress': 'answered'}
RANK = {'authorized': 0, 'ringing': 1, 'answered': 2}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def profile_hash(profile):
    return fingerprint({key: getattr(profile, key) for key in ('account_sid', 'api_key_sid', 'twiml_app_sid',
                        'shared_key_id', 'public_origin', 'caller_number', 'approved_destination')})


def event(db, intent_id, kind, details):
    return query(db, '''INSERT INTO staging.voice_events(intent_id,kind,fingerprint,details)
        VALUES (:id,:kind,:fingerprint,CAST(:details AS jsonb)) ON CONFLICT DO NOTHING RETURNING id''',
        id=intent_id, kind=kind, fingerprint=fingerprint(details), details=json.dumps(details)).first() is not None


def public(row):
    return {key: str(row[key]) if row[key] is not None else None
            for key in ('id', 'actor_id', 'state', 'outcome', 'created_at', 'expires_at', 'consumed_at', 'finished_at')}


def reserve(db, actor, identifier, profile):
    # authenticate/admin already holds the actor row lock. Database unique
    # indexes arbitrate competing users and sessions, including the same target.
    expired = query(db, '''UPDATE staging.voice_intents SET state='expired',finished_at=clock_timestamp()
        WHERE state='reserved' AND expires_at<=clock_timestamp() RETURNING id''').scalars().all()
    for old_id in expired:
        event(db, old_id, 'expired', {})
    previous = query(db, 'SELECT * FROM staging.voice_intents WHERE id=:id FOR UPDATE', id=identifier).mappings().first()
    binding = profile_hash(profile)
    if previous:
        if (previous['actor_id'] != actor['id'] or previous['session_hash'] != actor['session_hash']
                or previous['profile_hash'] != binding or previous['state'] != 'reserved'):
            raise HTTPException(409, 'Cette réservation ne peut pas être réutilisée.')
        return previous
    row = query(db, '''INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,
        account_sid,application_sid,caller_number,destination,expires_at)
        VALUES (:id,:actor,:session,:profile,:account,:application,:caller,:destination,
                clock_timestamp()+interval '2 minutes') RETURNING *''',
        id=identifier, actor=actor['id'], session=actor['session_hash'], profile=binding,
        account=profile.account_sid, application=profile.twiml_app_sid,
        caller=profile.caller_number, destination=profile.approved_destination).mappings().one()
    event(db, identifier, 'reserved', {})
    audit(db, actor['id'], 'voice.test_reserved', identifier)
    return row


def cancel(db, actor, identifier):
    row = query(db, 'SELECT * FROM staging.voice_intents WHERE id=:id FOR UPDATE', id=identifier).mappings().first()
    if not row or row['actor_id'] != actor['id'] or row['session_hash'] != actor['session_hash']:
        raise HTTPException(404, 'Réservation introuvable.')
    if row['state'] == 'cancelled':
        return public(row)
    if row['state'] != 'reserved':
        raise HTTPException(409, 'Un appel déjà autorisé doit être terminé avant de libérer sa réservation.')
    row = query(db, '''UPDATE staging.voice_intents SET state='cancelled',finished_at=clock_timestamp()
        WHERE id=:id RETURNING *''', id=identifier).mappings().one()
    event(db, identifier, 'cancelled', {})
    return public(row)


def bound(row, profile):
    if not row or row['profile_hash'] != profile_hash(profile) or row['account_sid'] != profile.account_sid:
        raise HTTPException(403, 'Notification sans appel associé.')
    return row


def consume(db, profile, params):
    identifier = UUID(params['Intent'])  # The entire form was authenticated first.
    lookup = query(db, 'SELECT actor_id,session_hash FROM staging.voice_intents WHERE id=:id', id=identifier).mappings().first()
    if lookup is None:
        return False
    # Keep the same user -> session -> intent lock order as human operations.
    user = query(db, 'SELECT * FROM staging.identity_users WHERE id=:id FOR UPDATE', id=lookup['actor_id']).mappings().first()
    session = query(db, '''SELECT token_hash FROM staging.identity_sessions
        WHERE token_hash=:hash AND user_id=:actor AND mfa_verified AND expires_at>clock_timestamp()
          AND last_seen_at>clock_timestamp()-interval '30 minutes' FOR UPDATE''',
        hash=lookup['session_hash'], actor=lookup['actor_id']).first()
    row = bound(query(db, 'SELECT * FROM staging.voice_intents WHERE id=:id FOR UPDATE', id=identifier).mappings().first(), profile)
    if row['state'] != 'reserved':
        return False  # Even the same CallSid cannot obtain a second Dial.
    valid = (user and user['is_active'] and user['role'] == 'admin' and user['mfa_secret'] and session
             and params['From'] == 'client:' + client_identity(row['actor_id'], identifier)
             and query(db, 'SELECT expires_at>clock_timestamp() FROM staging.voice_intents WHERE id=:id', id=identifier).scalar_one())
    if not valid:
        query(db, "UPDATE staging.voice_intents SET state='cancelled',finished_at=clock_timestamp() WHERE id=:id", id=identifier)
        event(db, identifier, 'authorization_denied', {})
        return False
    query(db, '''UPDATE staging.voice_intents SET state='authorized',parent_call_sid=:call,
        consumed_at=clock_timestamp() WHERE id=:id''', id=identifier, call=params['CallSid'])
    event(db, identifier, 'authorized', {'call_sid': params['CallSid']})
    return True


def integer(value, maximum):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,9}', value) or int(value) > maximum:
        raise HTTPException(400, 'Paramètre de notification invalide.')
    return int(value)


def attach_child(db, row, child):
    if not sid(child, 'CA') or child == row['parent_call_sid'] or row['child_call_sid'] not in (None, child):
        raise HTTPException(403, 'Notification sans appel associé.')
    if row['child_call_sid'] is None:
        query(db, 'UPDATE staging.voice_intents SET child_call_sid=:child WHERE id=:id', id=row['id'], child=child)


def advance(db, row, status, source_rank, sequence=None):
    if sequence is not None:
        if sequence <= row['last_child_sequence']:
            return
        query(db, 'UPDATE staging.voice_intents SET last_child_sequence=:sequence WHERE id=:id', id=row['id'], sequence=sequence)
    if status in OUTCOMES:
        if row['state'] in {'cancelled', 'expired'}:
            raise HTTPException(403, 'Notification sans appel associé.')
        if source_rank > row['outcome_rank']:
            query(db, '''UPDATE staging.voice_intents SET state='finished',outcome=:outcome,outcome_rank=:rank,
                finished_at=coalesce(finished_at,clock_timestamp()) WHERE id=:id''',
                id=row['id'], outcome=status, rank=source_rank)
    elif row['state'] not in TERMINAL and RANK[PROGRESS[status]] > RANK.get(row['state'], -1):
        query(db, 'UPDATE staging.voice_intents SET state=:state WHERE id=:id', id=row['id'], state=PROGRESS[status])


def notify(db, profile, kind, identifier, params):
    if kind == 'parent-status':
        row = query(db, 'SELECT * FROM staging.voice_intents WHERE parent_call_sid=:call FOR UPDATE', call=params['CallSid']).mappings().first()
    else:
        row = query(db, 'SELECT * FROM staging.voice_intents WHERE id=:id FOR UPDATE', id=identifier).mappings().first()
    row = bound(row, profile)
    if not row['parent_call_sid'] or row['state'] in {'reserved', 'cancelled', 'expired'}:
        raise HTTPException(403, 'Notification sans appel associé.')
    if kind == 'status':
        if (params.get('ParentCallSid') != row['parent_call_sid'] or params.get('To') != row['destination']
                or params.get('From') != row['caller_number']):
            raise HTTPException(403, 'Notification sans appel associé.')
        status = params.get('CallStatus')
        if status not in OUTCOMES | PROGRESS.keys():
            raise HTTPException(400, 'Statut de notification invalide.')
        sequence = integer(params.get('SequenceNumber'), 1000000)
        attach_child(db, row, params['CallSid'])
        details = {'call_sid': params['CallSid'], 'status': status, 'sequence': sequence}
        if event(db, row['id'], kind, details):
            advance(db, row, status, 2, sequence)
    elif kind in {'finish', 'parent-status'}:
        if params['CallSid'] != row['parent_call_sid']:
            raise HTTPException(403, 'Notification sans appel associé.')
        status = params.get('DialCallStatus') if kind == 'finish' else params.get('CallStatus')
        if status not in OUTCOMES:
            raise HTTPException(400, 'Statut final invalide.')
        child = params.get('DialCallSid') if kind == 'finish' else None
        if child:
            attach_child(db, row, child)
        details = {'call_sid': params['CallSid'], 'status': status, 'child_call_sid': child}
        if event(db, row['id'], kind, details):
            advance(db, row, status, 3 if kind == 'finish' else 1)
    elif kind == 'recording':
        # DialVerb recordings always belong to the parent leg (Twilio contract).
        # Parent binding is committed before Dial, so recording delivery can
        # precede every child status/finish without weakening ownership checks.
        if params['CallSid'] != row['parent_call_sid'] or params.get('RecordingSource') != 'DialVerb':
            raise HTTPException(403, 'Notification sans appel associé.')
        recording = params.get('RecordingSid')
        if not sid(recording, 'RE') or params.get('RecordingStatus') != 'completed':
            raise HTTPException(400, 'Enregistrement invalide.')
        duration = integer(params.get('RecordingDuration'), 600)
        channels = integer(params.get('RecordingChannels'), 2)
        if channels != 2:
            raise HTTPException(400, 'Enregistrement double canal requis.')
        previous = query(db, 'SELECT * FROM staging.voice_recordings WHERE sid=:sid', sid=recording).mappings().first()
        if previous and (previous['intent_id'] != row['id'] or previous['call_sid'] != params['CallSid']
                         or previous['duration'] != duration or previous['channels'] != channels):
            raise HTTPException(403, 'Enregistrement déjà associé à un autre appel ou différent.')
        query(db, '''INSERT INTO staging.voice_recordings(sid,intent_id,call_sid,duration,channels)
            VALUES (:sid,:id,:call,:duration,:channels) ON CONFLICT DO NOTHING''',
            sid=recording, id=row['id'], call=params['CallSid'], duration=duration, channels=channels)
        saved = query(db, 'SELECT * FROM staging.voice_recordings WHERE sid=:sid', sid=recording).mappings().one()
        if (saved['intent_id'] != row['id'] or saved['call_sid'] != params['CallSid']
                or saved['duration'] != duration or saved['channels'] != channels):
            raise HTTPException(403, 'Enregistrement déjà associé à un autre appel ou différent.')
        event(db, row['id'], kind, {'recording_sid': recording, 'call_sid': params['CallSid'],
                                  'duration': duration, 'channels': channels})
        query(db,'''INSERT INTO staging.voice_archive_jobs(recording_sid) VALUES (:sid)
            ON CONFLICT DO NOTHING''',sid=recording)
    else:
        raise HTTPException(400, 'Type de notification invalide.')


def history(db, identifier):
    row = query(db, 'SELECT * FROM staging.voice_intents WHERE id=:id', id=identifier).mappings().first()
    if not row:
        raise HTTPException(404, 'Réservation introuvable.')
    events = query(db, '''SELECT id,kind,details,created_at FROM staging.voice_events
        WHERE intent_id=:id ORDER BY id DESC LIMIT 100''', id=identifier).mappings().all()
    recordings = query(db, '''SELECT sid,state,duration,channels FROM staging.voice_recordings
        WHERE intent_id=:id ORDER BY created_at,sid''', id=identifier).mappings().all()
    return {'intent': public(row), 'events': [{**r, 'created_at': r['created_at'].isoformat()} for r in events],
            'recordings': [dict(r) for r in recordings]}

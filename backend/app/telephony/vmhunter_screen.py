"""Optional pre-bridge screening on the existing Dial/Number child leg.

The original Dial owns connection, recording, time limit and completion. The
sidecar only samples audio. Only this signed, durable whisper result can reject
an explicitly approved machine; it never redirects or creates a call.
"""
import logging
import os

import aiohttp
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from twilio.twiml.voice_response import VoiceResponse

from app.identity.service import query, audit
from app.telephony import service, vmhunter as vm
from app.telephony.twilio_voice import ManualVoiceProfile, webhook_url
from app.telephony.vmhunter_observer import policy_from_file, RPC_URL

log = logging.getLogger(__name__)
GREETING = 'Bonjour, ici Maisonverte Québec. Un conseiller vous répond dans un instant.'


def empty():
    # End only the Number's whisper: the original Dial then bridges the parties.
    return str(VoiceResponse())


def reject():
    response = VoiceResponse()
    response.hangup()
    return str(response)


def greeting(profile, identifier):
    response = VoiceResponse()
    wait = response.gather(input='dtmf', num_digits=1, timeout=1, finish_on_key='',
        action=webhook_url(profile, 'screen-result', identifier), method='POST',
        action_on_empty_result=True)
    wait.say(GREETING, language='fr-CA', voice='Polly.Chantal')
    # No Redirect/Pause/Stream: those verbs are unsupported in a Number whisper.
    return str(response)


def configured():
    path = os.environ.get('VMHUNTER_PILOT_FILE')
    if not path:
        return None
    try:
        pilot = policy_from_file(path)
        return pilot if pilot.enabled and pilot.mode == 'screen' and pilot.screening_approved else None
    except Exception:
        log.warning('vmhunter_screen_configuration_unavailable')
        return None


def prepare(db, profile, row):
    if not isinstance(profile, ManualVoiceProfile):
        return False
    pilot = configured()
    if pilot is None or not pilot.includes(row):
        return False
    service.event(db, row['id'], 'vmhunter.screen', {'pilot_id': str(pilot.identifier), 'mode': 'screen'})
    return True


def pending(db, identifier):
    # A fail-open DB outage in screen-start can leave no started event at all.
    # Anchor the first observed PSTN answer as well, not the reservation: ringing
    # can last much longer than the screening window. The same row lock used by
    # advance/begin serializes this append-only, idempotent recovery marker.
    if query(db, '''SELECT 1 FROM staging.voice_events s
        WHERE s.intent_id=:id AND s.kind='vmhunter.screen'
        AND NOT EXISTS (SELECT 1 FROM staging.voice_events b WHERE b.intent_id=s.intent_id
            AND b.kind IN ('vmhunter.screen.started','vmhunter.screen.waiting','vmhunter.screen.decision'))
        LIMIT 1''', id=identifier).first():
        service.event(db, identifier, 'vmhunter.screen.waiting', {})
    return query(db, '''SELECT 1 FROM staging.voice_events s
        WHERE s.intent_id=:id AND s.kind='vmhunter.screen'
        AND NOT EXISTS (SELECT 1 FROM staging.voice_events d
            WHERE d.intent_id=s.intent_id AND d.kind='vmhunter.screen.decision'
                AND d.details->>'action'='continue')
        AND ((SELECT min(b.created_at) FROM staging.voice_events b WHERE b.intent_id=s.intent_id
                AND b.kind IN ('vmhunter.screen.started','vmhunter.screen.waiting'))
                    >clock_timestamp()-interval '8 seconds'
            OR EXISTS (SELECT 1 FROM staging.voice_events d WHERE d.intent_id=s.intent_id
                AND d.kind='vmhunter.screen.decision' AND d.details->>'action'='hangup')) LIMIT 1''',
        id=identifier).first() is not None


def bound_child(db, profile, identifier, params):
    row = service.bound(query(db, 'SELECT * FROM staging.voice_intents WHERE id=:id FOR UPDATE',
                              id=identifier).mappings().first(), profile)
    if (not row['parent_call_sid'] or params.get('ParentCallSid') != row['parent_call_sid']
            or params.get('CallSid') == row['parent_call_sid']
            or row['child_call_sid'] not in (None, params['CallSid'])):
        raise HTTPException(403, 'Notification sans appel associé.')
    return dict(row)


def begin(engine, profile, identifier, params):
    with engine.begin() as db:
        row = bound_child(db, profile, identifier, params)
        snapshot = query(db, "SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.screen'",
                         id=identifier).scalar_one_or_none()
        decision = query(db, "SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.screen.decision'",
                         id=identifier).scalar_one_or_none()
        if not snapshot or row['state'] in service.TERMINAL:
            return {'finished': True}
        if decision:
            return {'decision': decision['action']}
        service.attach_child(db, row, params['CallSid'])
        row['child_call_sid'] = params['CallSid']
        first = service.event(db, identifier, 'vmhunter.screen.started', {'call_sid': params['CallSid']})
        fresh = query(db, """SELECT min(created_at)>clock_timestamp()-interval '8 seconds'
            FROM staging.voice_events WHERE intent_id=:id
                AND kind IN ('vmhunter.screen.started','vmhunter.screen.waiting')""",
            id=identifier).scalar_one()
        return {'first': first, 'fresh': fresh, 'row': row, 'pilot_id': snapshot['pilot_id']}


async def request_analysis(profile, identifier, call_sid, pilot_id):
    payload = {'intent_id': str(identifier), 'call_sid': call_sid, 'pilot_id': pilot_id}
    token = vm.ticket(profile.shared_key_secret, 'dispatch', payload)
    try:
        async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=1.25)) as session:
            async with session.post(RPC_URL, json={'ticket': token}, allow_redirects=False) as response:
                raw = await response.content.read(129)
                value = vm.object_json(raw)
                return (response.status == 202 and len(raw) <= 128
                        and set(value) == {'accepted'} and value['accepted'] is True)
    except Exception:
        log.warning('vmhunter_screen_analysis_unavailable')
        return False


def complete(engine, profile, identifier, params, *, force_continue=False):
    with engine.begin() as db:
        row = bound_child(db, profile, identifier, params)
        if row['state'] in service.TERMINAL:
            return empty()
        snapshot = query(db, "SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.screen'",
                         id=identifier).scalar_one_or_none()
        if not snapshot:
            return empty()
        if row['child_call_sid'] != params['CallSid']:
            raise HTTPException(403, 'Notification sans appel associé.')
        previous = query(db, "SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.screen.decision'",
                         id=identifier).scalar_one_or_none()
        if previous:
            return reject() if previous['action'] == 'hangup' else empty()
        current = configured()
        allowed = (current is not None and str(current.identifier) == snapshot['pilot_id']
                   and current.includes(row))
        fresh = query(db, """SELECT min(created_at)>clock_timestamp()-interval '8 seconds'
            FROM staging.voice_events WHERE intent_id=:id
                AND kind IN ('vmhunter.screen.started','vmhunter.screen.waiting')""",
            id=identifier).scalar_one_or_none()
        result = query(db, "SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.result'",
                       id=identifier).scalar_one_or_none()
        action = 'continue'
        reason = 'unavailable_or_pending'
        if (not force_continue and not params.get('Digits') and allowed and fresh
                and result and result.get('pilot_id') == snapshot['pilot_id']):
            action = vm.screen_action(vm.Result(result.get('status'), result.get('cause')),
                                      stop_confirmed=result.get('stream_stop_confirmed'))
            reason = 'verified_machine' if action == 'hangup' else 'human_or_uncertain'
        if params.get('Digits'):
            reason = 'caller_input'
        if force_continue or not allowed or not fresh:
            reason = 'bypass'
        service.event(db, identifier, 'vmhunter.screen.decision', {'action': action, 'reason': reason})
        if action == 'hangup':
            if not query(db, "SELECT 1 FROM staging.voice_events WHERE intent_id=:id AND kind='disposition.voicemail' LIMIT 1",
                         id=identifier).first():
                service.event(db, identifier, 'disposition.voicemail',
                    {'source': 'vmhunter', 'pilot_id': snapshot['pilot_id']})
                audit(db, row['actor_id'], 'voice.voicemail_auto', identifier)
            return reject()
        # A signed pre-bridge request proves a PSTN answer; no call is created.
        # The decision is written first so deferred in-progress can advance.
        service.advance(db, row, 'in-progress', 2)
        return empty()


async def start(request, profile, identifier, params):
    try:
        return await _start(request, profile, identifier, params)
    except IntegrityError:
        raise HTTPException(403, 'Notification sans appel associé.') from None
    except SQLAlchemyError:
        log.warning('vmhunter_screen_store_unavailable')
        return empty()


async def _start(request, profile, identifier, params):
    from starlette.concurrency import run_in_threadpool
    state = await run_in_threadpool(begin, request.app.state.engine, profile, identifier, params)
    if state.get('finished'):
        return empty()
    if 'decision' in state:
        return reject() if state['decision'] == 'hangup' else empty()
    pilot = configured()
    allowed = (pilot is not None and str(pilot.identifier) == state['pilot_id']
               and pilot.includes(state['row']) and state['fresh'])
    if allowed and (not state['first'] or await request_analysis(profile, identifier, params['CallSid'], state['pilot_id'])):
        return greeting(profile, identifier)
    return await run_in_threadpool(complete, request.app.state.engine, profile, identifier, params, force_continue=True)


async def finish(request, profile, identifier, params):
    from starlette.concurrency import run_in_threadpool
    try:
        return await run_in_threadpool(complete, request.app.state.engine, profile, identifier, params)
    except IntegrityError:
        raise HTTPException(403, 'Notification sans appel associé.') from None
    except SQLAlchemyError:
        log.warning('vmhunter_screen_store_unavailable')
        return empty()

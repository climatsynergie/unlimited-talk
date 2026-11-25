"""Opt-in audio-analysis sidecar. It can start/stop media streams, never calls.

Not enabled by the normal application or deployment. A signed child-answer
callback or signed pre-bridge hook queues a bounded internal analysis request.
The sidecar independently rechecks the campaign, agent, test number and budget.
"""
import asyncio
from contextlib import suppress
import json
import logging
import os
import time
from uuid import UUID, uuid4

import aiohttp
from aiohttp import web
from sqlalchemy import text

from app.telephony import vmhunter as vm
from app.telephony.configuration import private_bytes
from app.telephony.service import event
from app.telephony.twilio_voice import ManualVoiceProfile, sid

log = logging.getLogger(__name__)
RPC_URL = 'http://vmhunter:8080/private/observe'
MEDIA_PATH = '/api/telephony/vmhunter/media'


def policy_from_file(path):
    return vm.Pilot.parse(vm.object_json(private_bytes(path)))


def policy_allows(db, pilot, row):
    """Campaign scope is a live database boundary, never a wildcard allowlist."""
    if pilot.scope != 'campaign':
        return pilot.includes(row)
    if not pilot.includes(row, campaign_member=True):
        return False
    member = db.execute(text('''SELECT 1 FROM staging.campaign_contacts cc
        JOIN staging.contacts ct ON ct.id=cc.contact_id
        JOIN staging.campaigns c ON c.id=cc.campaign_id AND c.is_active
        JOIN staging.campaign_agents a ON a.campaign_id=c.id AND a.user_id=:actor AND a.is_active
        JOIN staging.identity_users u ON u.id=a.user_id AND u.is_active
        WHERE cc.campaign_id=:campaign AND cc.contact_id=:contact AND cc.is_active
          AND ct.phone=:destination'''),
        {'campaign': row['campaign_id'], 'contact': row['contact_id'],
         'actor': row['actor_id'], 'destination': row['destination']}).first()
    return member is not None


async def dispatch(profile, identifier, params):
    """Best effort only: provider failures must not fail a signed call callback."""
    path = os.environ.get('VMHUNTER_PILOT_FILE')
    if not path or not isinstance(profile, ManualVoiceProfile) or params.get('CallStatus') != 'in-progress':
        return
    try:
        pilot = policy_from_file(path)
        if not pilot.enabled or pilot.mode != 'observe':
            return
        payload = {'intent_id': str(identifier), 'call_sid': params['CallSid'],
                   'pilot_id': str(pilot.identifier)}
        token = vm.ticket(profile.shared_key_secret, 'dispatch', payload)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1), trust_env=False) as session:
            async with session.post(RPC_URL, json={'ticket': token}, allow_redirects=False) as response:
                await response.content.read(128)
                if response.status != 202:
                    log.warning('vmhunter_observation_unavailable')
    except Exception:
        # No token, customer audio, number, provider body or exception text.
        log.warning('vmhunter_observation_unavailable')


class Store:
    def __init__(self, engine, profile, pilot):
        self.engine, self.profile, self.pilot = engine, profile, pilot

    def claim(self, payload):
        identifier, call, pilot_id = parse_payload(payload)
        if pilot_id != self.pilot.identifier:
            return None
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL lock_timeout='250ms'"))
            db.execute(text("SET LOCAL statement_timeout='1500ms'"))
            # One small global budget lock, no CRM/dialer/user row locks.
            db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,78213))'),
                       {'key': 'vmhunter/' + self.profile.account_sid})
            row = db.execute(text('''SELECT i.* FROM staging.voice_intents i
                JOIN staging.campaigns c ON c.id=i.campaign_id AND c.is_active
                JOIN staging.campaign_agents a ON a.campaign_id=i.campaign_id AND a.user_id=i.actor_id AND a.is_active
                JOIN staging.identity_users u ON u.id=i.actor_id AND u.is_active
                WHERE i.id=:id AND i.account_sid=:account AND i.child_call_sid=:call
                FOR UPDATE OF i'''), {'id': identifier, 'account': self.profile.account_sid, 'call': call}).mappings().first()
            if not row or not policy_allows(db, self.pilot, row):
                return None
            if self.pilot.mode == 'screen':
                snapshot = db.execute(text("SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.screen'"),
                                      {'id': identifier}).scalar_one_or_none()
                started = db.execute(text("SELECT 1 FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.screen.started'"),
                                     {'id': identifier}).first()
                decided = db.execute(text("SELECT 1 FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.screen.decision'"),
                                     {'id': identifier}).first()
                if (snapshot != {'pilot_id': str(pilot_id), 'mode': 'screen'}
                        or not started or decided or not self.pilot.screening_approved):
                    return None
            existing = db.execute(text("SELECT 1 FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.claim' LIMIT 1"),
                                  {'id': identifier}).first()
            if existing:
                return None
            # A restart must not reset the circuit after an unconfirmed stop or
            # a process death. These append-only facts require operator review.
            unresolved = db.execute(text('''SELECT 1 FROM staging.voice_events c
                JOIN staging.voice_intents i ON i.id=c.intent_id
                WHERE i.campaign_id=:campaign AND i.account_sid=:account
                AND c.kind='vmhunter.claim'
                AND NOT EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
                    AND r.kind='vmhunter.result' AND r.details->>'stream_stop_confirmed'='true')
                AND (c.created_at<clock_timestamp()-interval '20 seconds'
                    OR EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
                        AND r.kind='vmhunter.result')) LIMIT 1'''),
                {'campaign': vm.PILOT_CAMPAIGN, 'account': self.profile.account_sid}).first()
            if unresolved:
                return None
            used = db.execute(text('''SELECT count(*) FROM (
                SELECT 1 FROM staging.voice_intents i JOIN staging.voice_events c ON c.intent_id=i.id
                WHERE i.campaign_id=:campaign AND i.account_sid=:account AND c.kind='vmhunter.claim'
                  AND c.details->>'pilot_id'=:pilot LIMIT :budget) used'''),
                {'campaign': vm.PILOT_CAMPAIGN, 'account': self.profile.account_sid,
                 'pilot': str(pilot_id), 'budget': self.pilot.max_analyses}).scalar_one()
            active = db.execute(text('''SELECT count(*) FROM staging.voice_events c
                JOIN staging.voice_intents i ON i.id=c.intent_id
                WHERE i.account_sid=:account AND i.campaign_id=:campaign
                AND i.created_at>clock_timestamp()-interval '35 minutes'
                AND c.kind='vmhunter.claim' AND c.created_at>clock_timestamp()-interval '20 seconds'
                AND NOT EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id AND r.kind='vmhunter.result')'''),
                {'account': self.profile.account_sid, 'campaign': vm.PILOT_CAMPAIGN}).scalar_one()
            if used >= self.pilot.max_analyses or active >= 2:
                return None
            nonce = uuid4().hex
            event(db, identifier, 'vmhunter.claim', {'pilot_id': str(pilot_id), 'call_sid': call, 'nonce': nonce})
            return {**payload, 'nonce': nonce}

    def result(self, payload, result, *, stop_confirmed):
        identifier, call, pilot_id = parse_payload(payload, nonce=True)
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL lock_timeout='250ms'"))
            db.execute(text("SET LOCAL statement_timeout='1500ms'"))
            db.execute(text('SELECT id FROM staging.voice_intents WHERE id=:id FOR UPDATE'), {'id': identifier})
            exists = db.execute(text("SELECT 1 FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.result' LIMIT 1"),
                                {'id': identifier}).first()
            claimed = db.execute(text("SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.claim'"),
                                 {'id': identifier}).scalar_one_or_none()
            if exists or claimed != {'pilot_id': str(pilot_id), 'call_sid': call, 'nonce': payload['nonce']}:
                return
            event(db, identifier, 'vmhunter.result', {
                'pilot_id': str(pilot_id), 'status': result.status, 'cause': result.cause,
                'action': result.observation_action, 'stream_stop_confirmed': stop_confirmed})


def parse_payload(payload, nonce=False):
    try:
        if (set(payload) != {'intent_id', 'call_sid', 'pilot_id'} | ({'nonce'} if nonce else set())
                or not sid(payload['call_sid'], 'CA')
                or nonce and (not isinstance(payload['nonce'], str) or len(payload['nonce']) != 32
                              or any(c not in '0123456789abcdef' for c in payload['nonce']))):
            raise vm.ProtocolError()
        return UUID(payload['intent_id']), payload['call_sid'], UUID(payload['pilot_id'])
    except (ValueError, TypeError, KeyError):
        raise vm.ProtocolError() from None


class Streams:
    """Only Media Streams creation/stopping; no call update/hangup capability."""
    def __init__(self, profile, session):
        self.profile, self.session = profile, session

    def url(self, call, stream=None):
        if not sid(call, 'CA') or stream is not None and not sid(stream, 'MZ'):
            raise vm.ProtocolError()
        return ('https://api.twilio.com/2010-04-01/Accounts/' + self.profile.account_sid
                + '/Calls/' + call + '/Streams' + ('/' + stream if stream else '') + '.json')

    async def start(self, payload, name, token):
        data = {'Url': self.profile.public_origin.replace('https://', 'wss://', 1) + MEDIA_PATH,
                'Track': 'inbound_track', 'Name': name,
                'Parameter1.Name': 'ticket', 'Parameter1.Value': token}
        async with self.session.post(self.url(payload['call_sid']), data=data,
                auth=aiohttp.BasicAuth(self.profile.api_key_sid, self.profile.api_key_secret),
                timeout=aiohttp.ClientTimeout(total=2), allow_redirects=False) as response:
            raw = await response.content.read(vm.MAX_MESSAGE + 1)
            if response.status != 201:
                raise vm.ProtocolError()
            result = vm.object_json(raw)
            if not sid(result.get('sid'), 'MZ') or result.get('call_sid') != payload['call_sid']:
                raise vm.ProtocolError()
            return result['sid']

    async def stop(self, call, stream):
        async with self.session.post(self.url(call, stream), data={'Status': 'stopped'},
                auth=aiohttp.BasicAuth(self.profile.api_key_sid, self.profile.api_key_secret),
                timeout=aiohttp.ClientTimeout(total=2), allow_redirects=False) as response:
            # A completed call can have already removed its stream.
            if response.status == 404:
                return True
            raw = await response.content.read(vm.MAX_MESSAGE + 1)
            if response.status != 200:
                return False
            result = vm.object_json(raw)
            return result.get('sid') == stream and result.get('status') == 'stopped'

    async def recover(self, call, name):
        """Resolve a timed-out creation by its unique name; never create again."""
        async with self.session.get(self.url(call), params={'PageSize': '4'},
                auth=aiohttp.BasicAuth(self.profile.api_key_sid, self.profile.api_key_secret),
                timeout=aiohttp.ClientTimeout(total=2), allow_redirects=False) as response:
            raw = await response.content.read(vm.MAX_MESSAGE + 1)
            if response.status != 200:
                return None
            value = vm.object_json(raw)
            streams = value.get('streams')
            if not isinstance(streams, list) or len(streams) > 4:
                return None
            found = [item.get('sid') for item in streams if isinstance(item, dict)
                     and item.get('name') == name and item.get('call_sid') == call]
            return found[0] if len(found) == 1 and sid(found[0], 'MZ') else None


class Observer:
    def __init__(self, profile, pilot, store, streams, provider, *, job_seconds=9, handshake_seconds=2, clock=time.monotonic):
        self.profile, self.pilot, self.store = profile, pilot, store
        self.streams, self.provider = streams, provider
        self.jobs = {}
        self.handshakes = 0
        self.degraded = False
        self.job_seconds, self.handshake_seconds = job_seconds, handshake_seconds
        self.clock, self.backoff_until = clock, 0.0

    async def observe(self, request):
        try:
            value = vm.object_json(await request.read())
            if set(value) != {'ticket'}:
                raise vm.ProtocolError()
            payload = vm.unticket(self.profile.shared_key_secret, 'dispatch', value['ticket'])
            parse_payload(payload)
        except (vm.ProtocolError, web.HTTPRequestEntityTooLarge):
            return web.Response(status=403)
        if (not self.pilot.enabled or self.degraded or len(self.jobs) >= 2
                or self.clock() < self.backoff_until):
            return web.json_response({'accepted': False}, status=202)
        try:
            claimed = await asyncio.to_thread(self.store.claim, payload)
        except Exception:
            log.warning('vmhunter_claim_unavailable')
            return web.json_response({'accepted': False}, status=202)
        if claimed:
            nonce = claimed['nonce']
            # No await between admission and registration of this local job.
            job = {'payload': claimed, 'stream': None, 'socket': None,
                   'done': asyncio.get_running_loop().create_future()}
            self.jobs[nonce] = job
            job['task'] = asyncio.create_task(self.run(job))
        return web.json_response({'accepted': bool(claimed)}, status=202)

    async def run(self, job):
        payload = job['payload']
        result = vm.Result('FAILED', 'stream_unavailable')
        stopped = False
        try:
            async with asyncio.timeout(self.job_seconds):
                token = vm.ticket(self.profile.shared_key_secret, 'media', payload)
                job['stream'] = await self.streams.start(payload, 'ut-vm-' + payload['nonce'], token)
                result = await job['done']
        except Exception:
            log.warning('vmhunter_stream_unavailable')
        finally:
            if result.status == 'FAILED':
                seconds = 30 if result.cause in {'AUTH_FAILED', 'LIMIT_REACHED', 'PERIOD_EXPIRED', 'NO_SUBSCRIPTION'} else 2
                self.backoff_until = max(self.backoff_until, self.clock() + seconds)
            # Always stop billing, including on timeout, disconnect or shutdown.
            if job['socket']:
                with suppress(Exception):
                    await job['socket'].close()
            if not job['stream']:
                with suppress(Exception):
                    job['stream'] = await self.streams.recover(payload['call_sid'], 'ut-vm-' + payload['nonce'])
            if job['stream']:
                try:
                    stopped = await self.streams.stop(payload['call_sid'], job['stream'])
                except Exception:
                    stopped = False
            if not stopped:
                self.degraded = True
                log.warning('vmhunter_stream_stop_unconfirmed')
            try:
                await asyncio.to_thread(self.store.result, payload, result, stop_confirmed=stopped)
            except Exception:
                log.warning('vmhunter_result_unavailable')
            self.jobs.pop(payload['nonce'], None)

    async def media(self, request):
        if self.handshakes >= 4 or not self.pilot.enabled:
            return web.Response(status=503)
        self.handshakes += 1
        ws = web.WebSocketResponse(max_msg_size=vm.MAX_MESSAGE, heartbeat=None, timeout=0.2)
        job = None
        try:
            await ws.prepare(request)
            async with asyncio.timeout(self.handshake_seconds):
                first = vm.object_json(await ws.receive_str())
                if first.get('event') != 'connected' or first.get('protocol') != 'Call' or first.get('version') != '1.0.0':
                    raise vm.ProtocolError()
                start = vm.object_json(await ws.receive_str())
                token = start.get('start', {}).get('customParameters', {}).get('ticket')
                payload = vm.unticket(self.profile.shared_key_secret, 'media', token)
                parse_payload(payload, nonce=True)
                job = self.jobs.get(payload['nonce'])
                if not job or job['payload'] != payload or job['socket'] is not None:
                    raise vm.ProtocolError()
                audio = vm.Audio(start, account=self.profile.account_sid, call=payload['call_sid'])
                if job['stream'] is not None and job['stream'] != audio.sid:
                    raise vm.ProtocolError()
                job['socket'], job['stream'] = ws, audio.sid

            async def frames():
                while audio.total < vm.MAX_AUDIO_BYTES:
                    message = vm.object_json(await ws.receive_str())
                    if message.get('event') == 'stop':
                        if message.get('streamSid') != audio.sid:
                            raise vm.ProtocolError()
                        break
                    for frame in audio.feed(message):
                        yield frame

            result = await self.provider.classify(payload['intent_id'], frames())
            if not job['done'].done():
                job['done'].set_result(result)
        except Exception:
            if job and job.get('socket') is ws and not job['done'].done():
                job['done'].set_result(vm.Result('FAILED', 'invalid_or_interrupted_media'))
        finally:
            self.handshakes -= 1
            if ws.prepared:
                await ws.close()
        return ws

    async def close(self):
        tasks = [job['task'] for job in self.jobs.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def application(observer):
    app = web.Application(client_max_size=vm.MAX_MESSAGE)
    app.router.add_post('/private/observe', observer.observe)
    app.router.add_get(MEDIA_PATH, observer.media)

    async def live(_request):
        return web.json_response({'status': 'alive', 'mode': observer.pilot.mode,
                                  'accepting': observer.pilot.enabled and not observer.degraded
                                      and observer.clock() >= observer.backoff_until})
    app.router.add_get('/health/live', live)

    async def cleanup(_app):
        await observer.close()
    app.on_cleanup.append(cleanup)
    return app


async def runtime():
    from app.database import make_engine
    from app.telephony.configuration import load_profile
    profile = load_profile()
    if not isinstance(profile, ManualVoiceProfile):
        raise RuntimeError('Profil manuel requis pour l’observation.')
    pilot = policy_from_file(os.environ['VMHUNTER_PILOT_FILE'])
    credentials = vm.object_json(private_bytes(os.environ['VMHUNTER_CREDENTIALS_FILE']))
    if (set(credentials) != {'version', 'mode', 'endpoint', 'api_key'}
            or type(credentials['version']) is not int or credentials['version'] != 1
            or credentials['mode'] != 'credentials_only' or credentials['endpoint'] != vm.ENDPOINT
            or not isinstance(credentials['api_key'], str) or not 1 <= len(credentials['api_key']) <= 2048
            or not credentials['api_key'].isascii() or not credentials['api_key'].isprintable()
            or any(c.isspace() for c in credentials['api_key'])):
        raise RuntimeError('Identifiants de détection invalides.')
    engine = make_engine()
    session = aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=8))
    observer = Observer(profile, pilot, Store(engine, profile, pilot), Streams(profile, session),
                        vm.Client(credentials['api_key'], session=session))
    app = application(observer)

    async def cleanup(_app):
        await session.close()
        engine.dispose()
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    # Access logs would expose arbitrary handshake paths. No audio/body logging.
    web.run_app(runtime(), host='0.0.0.0', port=8080, access_log=None)

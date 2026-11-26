"""Opt-in audio-analysis sidecar. It can start/stop media streams, never calls.

Not enabled by the normal application or deployment. A signed child-answer
callback or signed pre-bridge hook queues a bounded internal analysis request.
The sidecar independently rechecks the campaign, agent, test number and budget.
"""
import asyncio
from contextlib import suppress
from dataclasses import dataclass
import json
import logging
import os
import re
import struct
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
TERMINAL_PROVIDER_STATES = frozenset({'completed', 'busy', 'no-answer', 'failed', 'canceled'})


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


@dataclass(frozen=True)
class ProviderQuota:
    """The subscribed provider owns monthly usage and its renewal boundary.

    A routing policy's historical canary cap must not become a lifetime quota.
    This explicitly configured Free allowance never changes the subscription.
    """
    monthly_allowance: int = 5000

    def __post_init__(self):
        if type(self.monthly_allowance) is not int or self.monthly_allowance != 5000:
            raise ValueError('Quota gratuit VM Hunter invalide.')

    @classmethod
    def from_environment(cls, pilot):
        source = os.environ.get('VMHUNTER_QUOTA_SOURCE')
        allowance = os.environ.get('VMHUNTER_MONTHLY_ALLOWANCE')
        if source is None and allowance is None:
            return None
        if source != 'provider' or allowance != '5000':
            raise ValueError('Configuration du quota VM Hunter invalide.')
        value = cls()
        value.validate_scope(pilot)
        return value

    def validate_scope(self, pilot):
        if (pilot.scope != 'campaign' or pilot.mode != 'screen'
                or not pilot.audio_approved or not pilot.screening_approved):
            raise ValueError('Quota fournisseur réservé aux campagnes approuvées.')


class Store:
    def __init__(self, engine, profile, pilot, *, provider_quota=None):
        if provider_quota is not None:
            if not isinstance(provider_quota, ProviderQuota):
                raise ValueError('Quota fournisseur invalide.')
            provider_quota.validate_scope(pilot)
        self.engine, self.profile, self.pilot = engine, profile, pilot
        self.provider_quota = provider_quota

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
                WHERE i.account_sid=:account
                AND c.kind='vmhunter.claim'
                AND NOT EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
                    AND r.kind='vmhunter.result' AND r.details->>'stream_stop_confirmed'='true')
                AND NOT EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
                    AND r.kind='vmhunter.cleanup_verified'
                    AND i.state IN ('finished','cancelled','expired')
                    AND r.details->>'stream_stop_confirmed'='true'
                    AND r.details->>'call_sid'=c.details->>'call_sid'
                    AND r.details->>'nonce'=c.details->>'nonce'
                    AND r.details->>'provider_status' IN ('completed','busy','no-answer','failed','canceled'))
                AND (c.created_at<clock_timestamp()-interval '20 seconds'
                    OR EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
                        AND r.kind='vmhunter.result')) LIMIT 1'''),
                {'account': self.profile.account_sid}).first()
            if unresolved:
                return None
            # Keep explicit fixed canary budgets for legacy/test operation.
            # Subscription mode delegates the monthly quota and renewal to VM
            # Hunter, which refuses exhausted Free accounts without overages.
            used = 0
            if self.provider_quota is None:
                used = db.execute(text('''SELECT count(*) FROM (
                    SELECT 1 FROM staging.voice_intents i JOIN staging.voice_events c ON c.intent_id=i.id
                    WHERE i.account_sid=:account AND c.kind='vmhunter.claim'
                      AND c.details->>'pilot_id'=:pilot LIMIT :budget) used'''),
                    {'account': self.profile.account_sid,
                     'pilot': str(pilot_id), 'budget': self.pilot.max_analyses}).scalar_one()
            active = db.execute(text('''SELECT count(*) FROM staging.voice_events c
                JOIN staging.voice_intents i ON i.id=c.intent_id
                WHERE i.account_sid=:account
                AND i.created_at>clock_timestamp()-interval '35 minutes'
                AND c.kind='vmhunter.claim' AND c.created_at>clock_timestamp()-interval '20 seconds'
                AND NOT EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id AND r.kind='vmhunter.result')'''),
                {'account': self.profile.account_sid}).scalar_one()
            if (self.provider_quota is None and used >= self.pilot.max_analyses) or active >= 2:
                return None
            nonce = uuid4().hex
            event(db, identifier, 'vmhunter.claim', {'pilot_id': str(pilot_id), 'call_sid': call, 'nonce': nonce})
            return {**payload, 'nonce': nonce}

    def result(self, payload, result, *, stop_confirmed, audio_stats=None):
        identifier, call, pilot_id = parse_payload(payload, nonce=True)
        if audio_stats is not None and (not isinstance(audio_stats, dict)
                or set(audio_stats) != {'pcm_bytes','frames','signal_frames'}
                or any(type(v) is not int for v in audio_stats.values())
                or not 0 <= audio_stats['signal_frames'] <= audio_stats['frames'] <= vm.MAX_AUDIO_BYTES // 160
                or audio_stats['pcm_bytes'] != audio_stats['frames'] * 320):
            raise ValueError('Compteurs audio invalides.')
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
            details = {
                'pilot_id': str(pilot_id), 'status': result.status, 'cause': result.cause,
                'action': result.observation_action, 'stream_stop_confirmed': stop_confirmed}
            if audio_stats is not None:
                details['audio_stats'] = dict(audio_stats)
            event(db, identifier, 'vmhunter.result', details)


    def cleanup_candidates(self):
        """Bounded account-wide recovery also discovers interrupted prior workers."""
        with self.engine.connect() as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            db.execute(text("SET LOCAL statement_timeout='1500ms'"))
            rows = db.execute(text("""SELECT c.intent_id, c.details FROM staging.voice_events c
                JOIN staging.voice_intents i ON i.id=c.intent_id
                WHERE i.account_sid=:account AND c.kind='vmhunter.claim'
                AND NOT EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
                    AND r.kind='vmhunter.result' AND r.details->>'stream_stop_confirmed'='true')
                AND NOT EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
                    AND r.kind='vmhunter.cleanup_verified' AND i.state IN ('finished','cancelled','expired')
                    AND r.details->>'stream_stop_confirmed'='true'
                    AND r.details->>'call_sid'=c.details->>'call_sid'
                    AND r.details->>'nonce'=c.details->>'nonce'
                    AND r.details->>'provider_status' IN ('completed','busy','no-answer','failed','canceled'))
                AND (c.created_at<clock_timestamp()-interval '20 seconds'
                    OR EXISTS (SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
                        AND r.kind='vmhunter.result'))
                ORDER BY c.id LIMIT 10"""), {'account': self.profile.account_sid}).mappings()
            return [dict(row['details'], intent_id=str(row['intent_id'])) for row in rows]

    def verify_cleanup(self, payload, status):
        """Append a late authenticated terminal proof; never edit call/history facts."""
        identifier, call, pilot_id = parse_payload(payload, nonce=True)
        if not isinstance(status, str) or status not in TERMINAL_PROVIDER_STATES:
            return False
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL lock_timeout='250ms'"))
            db.execute(text("SET LOCAL statement_timeout='1500ms'"))
            row = db.execute(text('''SELECT state,child_call_sid FROM staging.voice_intents
                WHERE id=:id AND account_sid=:account FOR UPDATE'''),
                {'id': identifier, 'account': self.profile.account_sid}).mappings().first()
            claim = db.execute(text("SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.claim'"),
                {'id': identifier}).scalar_one_or_none()
            if (not row or row['state'] not in {'finished','cancelled','expired'}
                    or row['child_call_sid'] != call or claim != dict(pilot_id=str(pilot_id),call_sid=call,nonce=payload['nonce'])):
                return False
            event(db, identifier, 'vmhunter.cleanup_verified', dict(call_sid=call, nonce=payload['nonce'],
                stream_stop_confirmed=True, provider_status=status, source='automatic-terminal-recovery'))
            return True


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
    """Create/stop streams and read their bound call; never update/hang up calls."""
    def __init__(self, profile, session):
        self.profile, self.session = profile, session

    def url(self, call, stream=None):
        named = isinstance(stream, str) and re.fullmatch(r'ut-vm-[0-9a-f]{32}', stream)
        if not sid(call, 'CA') or stream is not None and not (sid(stream, 'MZ') or named):
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
            if response.status not in {200, 201}:
                code = None
                try:
                    value = vm.object_json(raw)
                    code = value.get('code') if type(value.get('code')) is int else None
                except vm.ProtocolError:
                    pass
                log.warning('vmhunter_stream_start_rejected http_status=%s error_code=%s', response.status, code)
                raise vm.ProtocolError()
            result = vm.object_json(raw)
            if not sid(result.get('sid'), 'MZ') or result.get('call_sid') != payload['call_sid']:
                log.warning('vmhunter_stream_binding_rejected sid_valid=%s call_matches=%s',
                            sid(result.get('sid'), 'MZ'), result.get('call_sid') == payload['call_sid'])
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

    async def terminal_status(self, call):
        """A verified terminal Call cannot retain a billable live Media Stream.

        A failed stop alone proves nothing. Read only the exact call already
        validated by url(); require its account, SID and terminal provider state.
        """
        url = self.url(call).removesuffix('/Streams.json') + '.json'
        async with self.session.get(url,
                auth=aiohttp.BasicAuth(self.profile.api_key_sid, self.profile.api_key_secret),
                timeout=aiohttp.ClientTimeout(total=2), allow_redirects=False) as response:
            if response.status != 200:
                return None
            value = vm.object_json(await response.content.read(vm.MAX_MESSAGE + 1))
            status = value.get('status')
            if (value.get('sid') == call and value.get('account_sid') == self.profile.account_sid
                    and isinstance(status, str) and status in TERMINAL_PROVIDER_STATES):
                return status
            return None

    async def call_finished(self, call):
        return await self.terminal_status(call) is not None

    async def recover(self, call, name):
        """Stop an uncertain creation by its unique name; never create again.

        Twilio has no GET/list Streams operation. Its supported stop endpoint
        accepts the stream name. A missing resource cannot prove an ambiguous
        creation was cleaned up, so 404 retains the durable safety circuit.
        """
        async with self.session.post(self.url(call, name), data={'Status': 'stopped'},
                auth=aiohttp.BasicAuth(self.profile.api_key_sid, self.profile.api_key_secret),
                timeout=aiohttp.ClientTimeout(total=2), allow_redirects=False) as response:
            raw = await response.content.read(vm.MAX_MESSAGE + 1)
            if response.status != 200:
                return None
            value = vm.object_json(raw)
            return (value['sid'] if sid(value.get('sid'), 'MZ') and value.get('name') == name
                    and value.get('call_sid') == call and value.get('status') == 'stopped' else None)


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
        except Exception as error:
            original = getattr(error, 'orig', None)
            code = getattr(original, 'sqlstate', None)
            log.warning('vmhunter_claim_error type=%s sqlstate=%s', type(error).__name__, code)
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
        phase = 'stream_create'
        try:
            async with asyncio.timeout(self.job_seconds):
                token = vm.ticket(self.profile.shared_key_secret, 'media', payload)
                job['stream'] = await self.streams.start(payload, 'ut-vm-' + payload['nonce'], token)
                phase = 'classification_wait'
                result = await job['done']
        except Exception as error:
            log.warning('vmhunter_stream_failure phase=%s type=%s stream_known=%s media_connected=%s',
                        phase, type(error).__name__, bool(job['stream']), job['socket'] is not None)
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
                # A fast callee hangup races the stop POST (Twilio 21220).
                # Preserve the circuit unless the authenticated provider read
                # independently proves this exact child call is terminal.
                try:
                    stopped = await self.streams.call_finished(payload['call_sid'])
                except Exception:
                    stopped = False
            if not stopped:
                self.degraded = True
                log.warning('vmhunter_stream_stop_unconfirmed')
            try:
                await asyncio.to_thread(self.store.result, payload, result, stop_confirmed=stopped,
                    **({'audio_stats': dict(job['audio_stats'])} if 'audio_stats' in job else {}))
            except Exception:
                log.warning('vmhunter_result_unavailable')
            self.jobs.pop(payload['nonce'], None)

    async def recover_cleanup(self):
        """Retry terminal reads after transient cleanup errors; never clear on a timer."""
        try:
            pending = await asyncio.to_thread(self.store.cleanup_candidates)
            if pending:
                self.degraded = True
            for payload in pending:
                parse_payload(payload, nonce=True)
                try:
                    status = await self.streams.terminal_status(payload['call_sid'])
                    if isinstance(status, str) and status in TERMINAL_PROVIDER_STATES:
                        await asyncio.to_thread(self.store.verify_cleanup, payload, status)
                except Exception as error:
                    log.warning('vmhunter_cleanup_retry_failed type=%s', type(error).__name__)
            if not self.jobs:
                remaining = await asyncio.to_thread(self.store.cleanup_candidates) if pending else pending
                self.degraded = bool(remaining)
        except Exception as error:
            self.degraded = True
            log.warning('vmhunter_cleanup_store_unavailable type=%s', type(error).__name__)

    async def media(self, request):
        if self.handshakes >= 4 or not self.pilot.enabled:
            return web.Response(status=503)
        self.handshakes += 1
        ws = web.WebSocketResponse(max_msg_size=vm.MAX_MESSAGE, heartbeat=None, timeout=0.2)
        job = None
        phase = 'upgrade'
        ticket_present = False
        try:
            await ws.prepare(request)
            async with asyncio.timeout(self.handshake_seconds):
                phase = 'connected_frame'
                first = vm.object_json(await ws.receive_str())
                # Twilio's live REST-created stream reports 0.2.0; the
                # current published example uses 1.0.0. Both still require the
                # signed ticket and exact account/call/stream/audio bindings.
                if (first.get('event') != 'connected' or first.get('protocol') != 'Call'
                        or first.get('version') not in ('0.2.0', '1.0.0')):
                    version = first.get('version')
                    safe_version = (version if isinstance(version, str)
                                    and re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}', version) else 'invalid')
                    log.warning('vmhunter_connected_rejected event_matches=%s protocol_matches=%s version=%s',
                                first.get('event') == 'connected', first.get('protocol') == 'Call', safe_version)
                    raise vm.ProtocolError()
                phase = 'start_frame'
                start = vm.object_json(await ws.receive_str())
                token = start.get('start', {}).get('customParameters', {}).get('ticket')
                ticket_present = isinstance(token, str) and bool(token)
                phase = 'capability'
                payload = vm.unticket(self.profile.shared_key_secret, 'media', token)
                parse_payload(payload, nonce=True)
                phase = 'admitted_job'
                job = self.jobs.get(payload['nonce'])
                if not job or job['payload'] != payload or job['socket'] is not None:
                    raise vm.ProtocolError()
                audio = vm.Audio(start, account=self.profile.account_sid, call=payload['call_sid'])
                if job['stream'] is not None and job['stream'] != audio.sid:
                    raise vm.ProtocolError()
                job['socket'], job['stream'] = ws, audio.sid

            job['audio_stats'] = dict(pcm_bytes=0, frames=0, signal_frames=0)

            async def frames():
                while audio.total < vm.MAX_AUDIO_BYTES:
                    message = vm.object_json(await ws.receive_str())
                    if message.get('event') == 'stop':
                        if message.get('streamSid') != audio.sid:
                            raise vm.ProtocolError()
                        break
                    for frame in audio.feed(message):
                        stats = job['audio_stats']
                        stats['frames'] += 1
                        stats['pcm_bytes'] += len(frame)
                        # Signal energy is a diagnostic, never a speech verdict.
                        stats['signal_frames'] += int(any(abs(v[0]) > 256 for v in struct.iter_unpack('<h', frame)))
                        yield frame

            phase = 'provider_audio'
            result = await self.provider.classify(payload['intent_id'], frames())
            if not job['done'].done():
                job['done'].set_result(result)
        except Exception as error:
            log.warning('vmhunter_media_rejected phase=%s type=%s ticket_present=%s',
                        phase, type(error).__name__, ticket_present)
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


def application(observer, *, recovery_interval=None):
    app = web.Application(client_max_size=vm.MAX_MESSAGE)
    if recovery_interval is not None:
        async def recovery_context(_app):
            await observer.recover_cleanup()
            async def watch():
                while True:
                    await asyncio.sleep(recovery_interval)
                    await observer.recover_cleanup()
            task = asyncio.create_task(watch())
            try:
                yield
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        app.cleanup_ctx.append(recovery_context)
    app.router.add_post('/private/observe', observer.observe)
    app.router.add_get(MEDIA_PATH, observer.media)

    async def live(_request):
        provider_quota = getattr(observer.store, 'provider_quota', None)
        quota = ({'source': 'vmhunter_subscription', 'monthly_allowance': provider_quota.monthly_allowance,
                  'internal_total_limit': None} if provider_quota is not None else
                 {'source': 'internal_canary', 'internal_total_limit': observer.pilot.max_analyses})
        return web.json_response({'status': 'alive', 'mode': observer.pilot.mode, 'quota': quota,
                                  'cleanup_pending': observer.degraded, 'active_analyses': len(observer.jobs),
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
    observer = Observer(profile, pilot, Store(engine, profile, pilot, provider_quota=ProviderQuota.from_environment(pilot)), Streams(profile, session),
                        vm.Client(credentials['api_key'], session=session))
    app = application(observer, recovery_interval=15)

    async def cleanup(_app):
        await session.close()
        engine.dispose()
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    # Access logs would expose arbitrary handshake paths. No audio/body logging.
    web.run_app(runtime(), host='0.0.0.0', port=8080, access_log=None)

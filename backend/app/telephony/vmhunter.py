"""Bounded VM Hunter protocol. No provider call creation or CRM mutation.

Cloud transport is intentionally separate from the phone state machine. The
first pilot observes classifications. Explicitly approved screening uses a
separate decision function which preserves uncertain and failed calls.
"""
import asyncio
import base64
from collections import deque
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import struct
import time
from uuid import UUID

import aiohttp

ENDPOINT = 'wss://app.vmhunter.com/ws'
PILOT_CAMPAIGN = UUID('2bdf5195-0b52-49b1-aecc-0caaf5459e77')
MAX_AUDIO_BYTES = 28000  # 3.5 seconds of mono 8kHz mu-law.
MAX_MESSAGE = 4096
FRAME_SAMPLES = 160
PROVIDER_CAUSES = frozenset({
    'HUMAN', 'MACHINE', 'MACHINE_BEEP', 'MACHINE_STATIC', 'DISCONNECT',
    'INITIALSILENCE', 'MAXWORD', 'AUTH_FAILED', 'LIMIT_REACHED', 'PERIOD_EXPIRED',
    'NO_SUBSCRIPTION', 'CPS_LIMIT', 'CHANNEL_LIMIT', 'CONFIG_TIMEOUT',
    'SPEECHLLM_ENGINE_UNAVAILABLE',
})


class ProtocolError(ValueError):
    def __init__(self):
        super().__init__('Protocole de détection invalide.')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError()
        result[key] = value
    return result


def object_json(raw):
    if not isinstance(raw, (str, bytes)) or len(raw) > MAX_MESSAGE:
        raise ProtocolError()
    try:
        result = json.loads(raw, object_pairs_hook=_unique,
                            parse_constant=lambda _value: (_ for _ in ()).throw(ProtocolError()))
        if not isinstance(result, dict):
            raise ProtocolError()
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise ProtocolError() from None


@dataclass(frozen=True)
class Result:
    status: str
    cause: str

    @property
    def observation_action(self):
        return 'continue'  # Never hang up, even a confident MACHINE result.


def verdict(raw):
    value = object_json(raw)
    status, cause = value.get('AMDSTATUS'), value.get('AMDCAUSE')
    if not isinstance(status, str) or not isinstance(cause, str):
        raise ProtocolError()
    # Recognized phrases can contain personal information: do not persist them.
    if cause.startswith('CALLGUARD_PHRASE'):
        cause = 'CALLGUARD'
    valid = {
        'HUMAN': {'HUMAN'},
        'MACHINE': {'MACHINE', 'MACHINE_BEEP', 'MACHINE_STATIC', 'DISCONNECT',
                    'INITIALSILENCE', 'MAXWORD', 'CALLGUARD'},
        'CALLGUARD': {'CALLGUARD'},
        'FAILED': PROVIDER_CAUSES - {'HUMAN', 'MACHINE', 'MACHINE_BEEP',
            'MACHINE_STATIC', 'DISCONNECT', 'INITIALSILENCE', 'MAXWORD'},
    }
    if status not in valid or cause not in valid[status]:
        raise ProtocolError()
    return Result(status, cause)


def _sample(code):
    value = (~code) & 255
    sample = ((value & 15) << 3) + 132
    sample <<= (value >> 4) & 7
    return 132 - sample if value & 128 else sample - 132


_PCM = tuple(struct.pack('<h', _sample(code)) for code in range(256))


def pcm(mulaw):
    """G.711 mu-law to s16le; independent of removed Python 3.13 audioop."""
    return b''.join(_PCM[code] for code in mulaw)


@dataclass(frozen=True)
class Pilot:
    identifier: UUID
    enabled: bool
    agents: frozenset
    max_analyses: int
    test_numbers: frozenset
    audio_approved: bool
    mode: str = 'observe'
    screening_approved: bool = False
    scope: str = 'pilot'
    campaigns: frozenset = frozenset({PILOT_CAMPAIGN})

    @classmethod
    def parse(cls, value):
        try:
            if not isinstance(value, dict):
                raise ProtocolError()
            version = value.get('version')
            screening = type(version) is int and version in {2, 3, 4}
            campaign_scope = type(version) is int and version in {3, 4}
            expected = {
                    'version', 'pilot_id', 'enabled', 'mode', 'campaign_id',
                    'agent_ids', 'max_analyses', 'test_numbers', 'audio_approved'}
            if version == 4:
                expected.remove('campaign_id')
                expected.add('campaign_ids')
            if screening:
                expected.add('screening_approved')
            if campaign_scope:
                expected.add('scope')
            if (set(value) != expected
                    or type(version) is not int or version not in {1, 2, 3, 4}
                    or campaign_scope and value['scope'] != 'campaign'
                    or value['mode'] != ('screen' if screening else 'observe')
                    or screening and type(value['screening_approved']) is not bool
                    or version != 4 and UUID(value['campaign_id']) != PILOT_CAMPAIGN
                    or type(value['enabled']) is not bool
                    or type(value['audio_approved']) is not bool
                    or type(value['max_analyses']) is not int
                    or not 1 <= value['max_analyses'] <= 1000
                    or not isinstance(value['agent_ids'], list)
                    or not isinstance(value['test_numbers'], list)):
                raise ProtocolError()
            if version == 4:
                values = value['campaign_ids']
                if not isinstance(values, list) or not 1 <= len(values) <= 20:
                    raise ProtocolError()
                campaigns = frozenset(UUID(item) for item in values)
                if len(campaigns) != len(values):
                    raise ProtocolError()
            else:
                campaigns = frozenset({PILOT_CAMPAIGN})
            agents = frozenset(UUID(item) for item in value['agent_ids'])
            numbers = frozenset(value['test_numbers'])
            if (len(agents) != len(value['agent_ids']) or len(agents) > 2
                    or len(numbers) != len(value['test_numbers']) or len(numbers) > 10
                    or any(not isinstance(number, str) or not re.fullmatch(r'\+[1-9][0-9]{8,14}', number)
                           for number in numbers)
                    or campaign_scope and (agents or numbers)
                    or value['enabled'] and ((not campaign_scope and (not agents or not numbers)) or not value['audio_approved']
                        or screening and not value['screening_approved'])):
                raise ProtocolError()
            return cls(UUID(value['pilot_id']), value['enabled'], agents,
                       value['max_analyses'], numbers, value['audio_approved'],
                       value['mode'], value.get('screening_approved', False),
                       'campaign' if campaign_scope else 'pilot', campaigns)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProtocolError() from None

    def includes(self, row, *, campaign_member=False):
        return bool(self.enabled and self.audio_approved
            and row.get('campaign_id') in self.campaigns
            and (self.scope == 'campaign' and campaign_member is True
                and row.get('actor_id') is not None and row.get('contact_id') is not None
                and isinstance(row.get('destination'), str)
                and re.fullmatch(r'\+[1-9][0-9]{8,14}', row['destination'])
                or self.scope == 'pilot' and row.get('actor_id') in self.agents
                    and row.get('destination') in self.test_numbers)
            and row.get('dialer_generation') is not None
            and row.get('state') in ({'authorized', 'ringing', 'answered'}
                                    if self.mode == 'screen' and self.screening_approved else {'answered'}))


def screen_action(result, *, stop_confirmed):
    """Only explicit machine/beep decisions with completed cleanup can reject.

    Silence, noise, cut-off speech, call screening, disconnected-number tones,
    provider failures and future/unknown causes must reach the agent.
    """
    return ('hangup' if stop_confirmed is True and result.status == 'MACHINE'
            and result.cause in {'MACHINE', 'MACHINE_BEEP'} else 'continue')


def ticket(secret, kind, payload, *, now=None):
    """Short-lived, domain-separated capability; never include it in a URL/log."""
    now = int(time.time() if now is None else now)
    raw = json.dumps({'kind': kind, 'iat': now, 'payload': payload},
                     sort_keys=True, separators=(',', ':')).encode()
    body = base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
    mac = hmac.new(secret.encode(), b'ut-vmhunter-v1\0' + body.encode(), hashlib.sha256).hexdigest()
    return body + '.' + mac


def unticket(secret, kind, token, *, now=None):
    try:
        if not isinstance(token, str) or len(token) > 2048:
            raise ProtocolError()
        body, mac = token.split('.')
        expected = hmac.new(secret.encode(), b'ut-vmhunter-v1\0' + body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ProtocolError()
        value = object_json(base64.b64decode(body + '=' * (-len(body) % 4), altchars=b'-_', validate=True))
        timestamp = int(time.time() if now is None else now)
        if (set(value) != {'kind', 'iat', 'payload'} or value['kind'] != kind
                or type(value['iat']) is not int or not 0 <= timestamp - value['iat'] <= 15
                or not isinstance(value['payload'], dict)):
            raise ProtocolError()
        return value['payload']
    except (ValueError, TypeError, UnicodeError):
        raise ProtocolError() from None


class Audio:
    """Validate an authenticated Twilio inbound track and bound its audio bytes."""
    def __init__(self, start, *, account, call):
        value = start.get('start', {})
        self.sid = value.get('streamSid')
        if (start.get('event') != 'start' or not isinstance(self.sid, str)
                or not re.fullmatch(r'MZ[0-9a-fA-F]{32}', self.sid)
                or value.get('accountSid') != account or value.get('callSid') != call
                or value.get('tracks') != ['inbound']
                or value.get('mediaFormat') != {'encoding': 'audio/x-mulaw', 'sampleRate': 8000, 'channels': 1}):
            raise ProtocolError()
        self.total = 0
        self.pending = b''
        self.chunk = 0
        self.timestamp = None
        self.previous_size = 0

    def feed(self, message):
        if message.get('event') != 'media' or message.get('streamSid') != self.sid:
            raise ProtocolError()
        value = message.get('media', {})
        try:
            if (value.get('track') != 'inbound'
                    or not isinstance(value.get('payload'), str) or len(value['payload']) > 2160
                    or not isinstance(value.get('chunk'), str) or not value['chunk'].isascii() or not value['chunk'].isdigit()
                    or not isinstance(value.get('timestamp'), str) or not value['timestamp'].isascii() or not value['timestamp'].isdigit()
                    or len(value['chunk']) > 9 or len(value['timestamp']) > 9):
                raise ProtocolError()
            chunk, timestamp = int(value['chunk']), int(value['timestamp'])
            data = base64.b64decode(value['payload'], validate=True)
            if (not 1 <= len(data) <= 1600 or chunk != self.chunk + 1
                    or self.timestamp is not None and timestamp != self.timestamp + self.previous_size // 8
                    or len(data) % 8):
                raise ProtocolError()
            self.chunk, self.timestamp, self.previous_size = chunk, timestamp, len(data)
            data = data[:MAX_AUDIO_BYTES - self.total]
            self.total += len(data)
            self.pending += data
            frames = []
            while len(self.pending) >= FRAME_SAMPLES:
                frames.append(pcm(self.pending[:FRAME_SAMPLES]))
                self.pending = self.pending[FRAME_SAMPLES:]
            return frames
        except (ValueError, TypeError, KeyError):
            raise ProtocolError() from None


class StartLimiter:
    """Non-blocking rolling-second gate, shared by this worker's API client.

    Called on the event loop immediately before a provider config frame. No
    waiting caller, queued audio, background timer or credentials are retained.
    Durable account-wide admission is independently bounded by Store.claim.
    """
    def __init__(self, calls_per_second, *, clock=time.monotonic):
        if type(calls_per_second) is not int or not 1 <= calls_per_second <= 5:
            raise ValueError('Débit VM Hunter invalide.')
        self.limit, self.clock = calls_per_second, clock
        self.starts = deque()

    def allow(self):
        now = self.clock()
        while self.starts and self.starts[0] <= now - 1:
            self.starts.popleft()
        if len(self.starts) >= self.limit:
            return False
        self.starts.append(now)
        return True


class Client:
    def __init__(self, api_key, *, session, endpoint=ENDPOINT, start_limiter=None):
        self._key, self._session, self._endpoint = api_key, session, endpoint
        self._start_limiter = start_limiter

    async def classify(self, identifier, audio, *, seconds=5):
        """Read while sending; cancel the sender on the first verdict or failure."""
        try:
            async with asyncio.timeout(seconds):
                async with self._session.ws_connect(self._endpoint, max_msg_size=MAX_MESSAGE,
                        timeout=aiohttp.ClientWSTimeout(ws_close=0.2), autoping=True) as ws:
                    if self._start_limiter is not None and not self._start_limiter.allow():
                        return Result('FAILED', 'local_rate_limit')
                    await ws.send_json({'config': {'vid': str(identifier), 'api_key': self._key,
                                                  'sample_rate': 8000, 'bytes_per_sample': 2}})

                    async def send():
                        count = 0
                        async for frame in audio:
                            if not isinstance(frame, bytes) or not frame or len(frame) > 320 or len(frame) % 2:
                                raise ProtocolError()
                            count += len(frame)
                            if count > MAX_AUDIO_BYTES * 2:
                                raise ProtocolError()
                            await ws.send_bytes(frame)
                        await ws.send_json({'eof': 1})

                    async def receive():
                        message = await ws.receive()
                        if message.type != aiohttp.WSMsgType.TEXT:
                            raise ProtocolError()
                        return verdict(message.data)

                    sender, reader = asyncio.create_task(send()), asyncio.create_task(receive())
                    try:
                        done, _ = await asyncio.wait({sender, reader}, return_when=asyncio.FIRST_COMPLETED)
                        if reader in done:
                            return reader.result()
                        sender.result()  # Never mask an audio protocol failure.
                        return await reader
                    finally:
                        for task in (sender, reader):
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(sender, reader, return_exceptions=True)
        except (TimeoutError, aiohttp.ClientError, OSError, ProtocolError):
            return Result('FAILED', 'transport_or_protocol')

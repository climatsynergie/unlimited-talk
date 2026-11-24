"""Bounded VM Hunter protocol. No call creation, hangup or CRM mutation.

Cloud transport is intentionally separate from the phone state machine. The
first pilot observes classifications; it cannot change call dispositions.
"""
import asyncio
import base64
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

    @classmethod
    def parse(cls, value):
        try:
            if (not isinstance(value, dict) or set(value) != {
                    'version', 'pilot_id', 'enabled', 'mode', 'campaign_id',
                    'agent_ids', 'max_analyses', 'test_numbers', 'audio_approved'}
                    or type(value['version']) is not int or value['version'] != 1
                    or value['mode'] != 'observe'
                    or UUID(value['campaign_id']) != PILOT_CAMPAIGN
                    or type(value['enabled']) is not bool
                    or type(value['audio_approved']) is not bool
                    or type(value['max_analyses']) is not int
                    or not 1 <= value['max_analyses'] <= 1000
                    or not isinstance(value['agent_ids'], list)
                    or not isinstance(value['test_numbers'], list)):
                raise ProtocolError()
            agents = frozenset(UUID(item) for item in value['agent_ids'])
            numbers = frozenset(value['test_numbers'])
            if (len(agents) != len(value['agent_ids']) or len(agents) > 2
                    or len(numbers) != len(value['test_numbers']) or len(numbers) > 10
                    or any(not isinstance(number, str) or not re.fullmatch(r'\+[1-9][0-9]{8,14}', number)
                           for number in numbers)
                    or value['enabled'] and (not agents or not numbers or not value['audio_approved'])):
                raise ProtocolError()
            return cls(UUID(value['pilot_id']), value['enabled'], agents,
                       value['max_analyses'], numbers, value['audio_approved'])
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProtocolError() from None

    def includes(self, row):
        return bool(self.enabled and self.audio_approved
            and row.get('campaign_id') == PILOT_CAMPAIGN
            and row.get('actor_id') in self.agents
            and row.get('destination') in self.test_numbers
            and row.get('dialer_generation') is not None
            and row.get('state') == 'answered')


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


class Client:
    def __init__(self, api_key, *, session, endpoint=ENDPOINT):
        self._key, self._session, self._endpoint = api_key, session, endpoint

    async def classify(self, identifier, audio, *, seconds=5):
        """Read while sending; cancel the sender on the first verdict or failure."""
        try:
            async with asyncio.timeout(seconds):
                async with self._session.ws_connect(self._endpoint, max_msg_size=MAX_MESSAGE,
                        timeout=aiohttp.ClientWSTimeout(ws_close=0.2), autoping=True) as ws:
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

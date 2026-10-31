"""Recover missing callback results through bounded, GET-only provider reads.

Never originate, redirect, end, or retry a call. Provider failure, absence or an
ambiguous relationship keeps the reservation occupied. Network work happens
outside database transactions; applying an observation locks and rechecks the
original intent so a concurrent webhook always keeps its authority.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import base64
import json
import logging
import os
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urlencode
import urllib.error
import urllib.request
from uuid import UUID

from app.identity.service import query
from app.telephony import service
from app.telephony.twilio_voice import ControlledVoiceProfile, client_identity, sid

logger = logging.getLogger(__name__)
ACTIVE = frozenset({'authorized', 'ringing', 'answered'})
KNOWN_STATUSES = service.OUTCOMES | service.PROGRESS.keys()
MAX_RESPONSE_BYTES = 65536
MAX_BATCH = 20
ERROR_REASONS = frozenset({'invalid_reservation', 'invalid_profile', 'endpoint_refused', 'redirect_refused',
    'provider_response_invalid', 'provider_response_too_large', 'provider_authentication_failed',
    'provider_read_forbidden', 'provider_call_not_found', 'provider_rate_limited', 'provider_unavailable',
    'provider_identity_mismatch', 'provider_child_mismatch', 'provider_parent_mismatch',
    'provider_children_ambiguous', 'invalid_observation'})


class ProviderReadError(ValueError):
    """Reason codes only: never retain a provider response or credentials."""


@dataclass(frozen=True, repr=False)
class PendingCall:
    id: UUID
    actor_id: UUID
    profile_hash: str
    account_sid: str
    caller_number: str
    destination: str
    parent_call_sid: str
    child_call_sid: str | None

    def check(self, profile):
        if (not isinstance(self.id, UUID) or not isinstance(self.actor_id, UUID)
                or self.profile_hash != service.profile_hash(profile) or self.account_sid != profile.account_sid
                or self.caller_number != profile.caller_number or self.destination != profile.approved_destination
                or not sid(self.parent_call_sid, 'CA')
                or (self.child_call_sid is not None and (not sid(self.child_call_sid, 'CA')
                                                        or self.child_call_sid == self.parent_call_sid))):
            raise ProviderReadError('invalid_reservation')


@dataclass(frozen=True, repr=False)
class Observation:
    pending: PendingCall
    parent_status: str
    child_call_sid: str | None
    child_status: str | None

    @property
    def terminal(self):
        return self.parent_status in service.OUTCOMES and (self.child_call_sid is None or self.child_status in service.OUTCOMES)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderReadError('redirect_refused')


class ReadOnlyCalls:
    def __init__(self, profile: ControlledVoiceProfile, send=None, gateway=None, token=None):
        if not isinstance(profile, ControlledVoiceProfile):
            raise ProviderReadError('invalid_profile')
        self.profile = profile
        self.base = 'https://api.twilio.com/2010-04-01/Accounts/' + profile.account_sid
        self.send = send
        self.authorization = 'Basic ' + base64.b64encode((profile.api_key_sid + ':' + profile.api_key_secret).encode()).decode()
        if gateway is not None:
            if gateway != 'http://172.30.8.1:8112' or not isinstance(token, str) or not re.fullmatch('[0-9a-f]{64}', token):
                raise ProviderReadError('invalid_profile')
            self.base = gateway + '/2010-04-01/Accounts/' + profile.account_sid
            self.authorization = 'Bearer ' + token

    def _get(self, suffix):
        # This allowlist exists in addition to validation of the reservation and
        # relationships. Neither URLs supplied in responses nor a POST can pass.
        if not (re.fullmatch(r'/Calls/CA[0-9a-fA-F]{32}\.json', suffix)
                or re.fullmatch(r'/Calls\.json\?ParentCallSid=CA[0-9a-fA-F]{32}&PageSize=2', suffix)):
            raise ProviderReadError('endpoint_refused')
        request = urllib.request.Request(self.base + suffix, method='GET', headers={
            'Authorization': self.authorization, 'Accept': 'application/json',
            'Cache-Control': 'no-cache', 'User-Agent': 'Unlimited-Talks-call-reconciliation/1'})
        try:
            if self.send is not None:
                result = self.send(request)
            else:
                opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
                with opener.open(request, timeout=5) as response:
                    if response.status != 200:
                        raise ProviderReadError('provider_response_invalid')
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ProviderReadError('provider_response_too_large')
                result = json.loads(raw)
        except ProviderReadError:
            raise
        except urllib.error.HTTPError as error:
            reason = {401: 'provider_authentication_failed', 403: 'provider_read_forbidden',
                      404: 'provider_call_not_found', 429: 'provider_rate_limited'}.get(error.code, 'provider_unavailable')
            raise ProviderReadError(reason) from None
        except Exception:
            raise ProviderReadError('provider_unavailable') from None
        if not isinstance(result, dict):
            raise ProviderReadError('provider_response_invalid')
        return result

    def _validate(self, data, expected_sid, pending, child=False):
        if (data.get('account_sid') != pending.account_sid or data.get('sid') != expected_sid
                or not isinstance(data.get('status'), str) or data['status'] not in KNOWN_STATUSES):
            raise ProviderReadError('provider_identity_mismatch')
        if child:
            if (data.get('parent_call_sid') != pending.parent_call_sid or data.get('direction') != 'outbound-dial'
                    or data.get('from') != pending.caller_number or data.get('to') != pending.destination):
                raise ProviderReadError('provider_child_mismatch')
        elif ('parent_call_sid' not in data or data['parent_call_sid'] is not None
              or data.get('from') != 'client:' + client_identity(pending.actor_id, pending.id)):
            raise ProviderReadError('provider_parent_mismatch')

    def read(self, pending: PendingCall):
        pending.check(self.profile)
        # Never filter by the expected phone: that could hide an unexpected
        # second child. Any ambiguity or incomplete page requires review.
        listing = self._get('/Calls.json?' + urlencode({'ParentCallSid': pending.parent_call_sid, 'PageSize': 2}))
        children = listing.get('calls')
        if ('next_page_uri' not in listing or listing['next_page_uri'] not in (None, '')
                or not isinstance(children, list) or len(children) > 1):
            raise ProviderReadError('provider_children_ambiguous')
        child_id = pending.child_call_sid
        if children:
            child = children[0]
            if not isinstance(child, dict) or not sid(child.get('sid'), 'CA') or child['sid'] == pending.parent_call_sid:
                raise ProviderReadError('provider_child_mismatch')
            self._validate(child, child['sid'], pending, child=True)
            if child_id is not None and child['sid'] != child_id:
                raise ProviderReadError('provider_child_mismatch')
            child_id = child['sid']
        child_status = None
        if child_id is not None:
            # A known child is read even if a filtered list temporarily omits it.
            child = self._get('/Calls/' + child_id + '.json')
            self._validate(child, child_id, pending, child=True)
            child_status = child['status']
        parent = self._get('/Calls/' + pending.parent_call_sid + '.json')
        self._validate(parent, pending.parent_call_sid, pending)
        return Observation(pending, parent['status'], child_id, child_status)


def candidates(engine, profile, limit=MAX_BATCH):
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
        raise ValueError('Taille de lot invalide.')
    with engine.connect() as db:
        rows = query(db, '''SELECT id,actor_id,profile_hash,account_sid,caller_number,destination,parent_call_sid,child_call_sid
            FROM staging.voice_intents WHERE state IN ('authorized','ringing','answered')
              AND consumed_at<clock_timestamp()-interval '20 seconds' AND profile_hash=:profile
              AND account_sid=:account ORDER BY consumed_at,id LIMIT :limit''',
            profile=service.profile_hash(profile), account=profile.account_sid, limit=limit).mappings().all()
    return [PendingCall(**row) for row in rows]


def apply_observation(engine, profile, observed):
    pending = observed.pending
    pending.check(profile)
    if (not isinstance(observed.parent_status, str) or observed.parent_status not in KNOWN_STATUSES
            or (observed.child_call_sid is None and observed.child_status is not None)
            or (observed.child_call_sid is not None and (not sid(observed.child_call_sid, 'CA')
                or observed.child_call_sid == pending.parent_call_sid or not isinstance(observed.child_status, str)
                or observed.child_status not in KNOWN_STATUSES))
            or pending.child_call_sid not in (None, observed.child_call_sid)):
        raise ProviderReadError('invalid_observation')
    with engine.begin() as db:
        row = query(db, 'SELECT * FROM staging.voice_intents WHERE id=:id FOR UPDATE', id=pending.id).mappings().first()
        if not row or row['state'] not in ACTIVE:
            return 'resolved_elsewhere'
        # Recheck frozen ownership after network I/O; a newer callback can bind a
        # child while the provider read is running. Unobserved children block us.
        if (any(row[key] != getattr(pending, key) for key in
                ('actor_id','profile_hash','account_sid','caller_number','destination','parent_call_sid'))
                or row['child_call_sid'] not in (None, observed.child_call_sid)):
            return 'stale_observation'
        if observed.child_call_sid is not None:
            service.attach_child(db, row, observed.child_call_sid)
        details = {'parent_status': observed.parent_status, 'child_call_sid': observed.child_call_sid,
                   'child_status': observed.child_status, 'terminal': observed.terminal}
        service.event(db, row['id'], 'reconciliation.observed', details)
        if observed.terminal:
            outcome = observed.child_status or observed.parent_status
            service.advance(db, row, outcome, 2 if observed.child_call_sid else 1)
            return 'recovered'
        # Recover useful progress but never release on a terminal child while its
        # parent is still active. Unknown or inconsistent state stays occupied.
        if observed.child_status in service.PROGRESS:
            service.advance(db, row, observed.child_status, 0)
        return 'pending'


def configured_provider(profile):
    if os.environ.get('DB_DEPLOYMENT', 'local') == 'managed':
        from app.telephony.configuration import private_bytes
        try:
            token = private_bytes(os.environ['VOICE_READ_TOKEN_FILE']).decode().strip()
            return ReadOnlyCalls(profile, gateway=os.environ['VOICE_READ_GATEWAY_URL'], token=token)
        except Exception:
            raise ProviderReadError('invalid_profile') from None
    return ReadOnlyCalls(profile)


def reconcile_once(engine, profile, provider=None):
    if profile is None:
        return {'checked': 0, 'recovered': 0, 'pending': 0, 'failed': 0, 'stale': 0, 'errors': {}}
    provider = configured_provider(profile) if provider is None else provider
    pending = candidates(engine, profile)
    result = {'checked': len(pending), 'recovered': 0, 'pending': 0, 'failed': 0, 'stale': 0, 'errors': {}}
    # At most four I/O operations at once; no DB connection/row lock is kept
    # during those reads. Duplicate workers may read twice, never dial twice.
    with ThreadPoolExecutor(max_workers=4) as executor:
        reads = {executor.submit(provider.read, call): call for call in pending}
        for future in as_completed(reads):
            try:
                status = apply_observation(engine, profile, future.result())
            except Exception as error:
                reason = error.args[0] if isinstance(error, ProviderReadError) and error.args else None
                reason = reason if isinstance(reason, str) and reason in ERROR_REASONS else 'unexpected_error'
                result['failed'] += 1
                result['errors'][reason] = result['errors'].get(reason, 0) + 1
                continue
            key = status if status in {'recovered', 'pending'} else 'stale'
            result[key] += 1
    return result


def main():
    from app.database import make_engine
    from app.telephony.configuration import load_profile
    profile = load_profile()
    if profile is None:
        # Local CI and explicitly disabled installations stay idle without
        # loading credentials, touching PG or contacting any provider.
        while True:
            Path('/tmp/voice-reconciliation-heartbeat').touch()
            time.sleep(10)
    engine = make_engine()
    provider = configured_provider(profile)
    try:
        while True:
            try:
                result = reconcile_once(engine, profile, provider)
                if result['failed']:
                    logger.warning('Rapprochement Voice en attente : %s', result)
                else:
                    Path('/tmp/voice-reconciliation-heartbeat').touch()
            except Exception:
                logger.warning('Rapprochement Voice à reprendre.')
            time.sleep(10)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()

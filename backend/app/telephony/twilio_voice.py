"""Offline Voice SDK primitives for an explicitly authorized controlled call.

These functions do not authorize a call, persist its intent, install a webhook,
change account settings or send provider requests. A durable service must check
session ownership, expiry and atomic one-time redemption before returning TwiML.
"""
from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from starlette.datastructures import FormData
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse

TOKEN_TTL_SECONDS = 300
MAX_TEST_CALL_SECONDS = 180
MAX_WEBHOOK_BYTES = 16384
FIXED_HOOK_KINDS = frozenset({'voice', 'parent-status'})
INTENT_HOOK_KINDS = frozenset({'status', 'recording', 'finish'})
HOOK_KINDS = FIXED_HOOK_KINDS | INTENT_HOOK_KINDS
CRITICAL_FIELDS = frozenset({'AccountSid', 'CallSid', 'ParentCallSid', 'From', 'To', 'Intent'})


class VoiceConfigurationError(ValueError):
    pass


class VoiceWebhookError(ValueError):
    pass


def sid(value, prefix):
    return isinstance(value, str) and re.fullmatch(prefix + r'[0-9a-fA-F]{32}', value) is not None


def secret(value):
    return (isinstance(value, str) and 32 <= len(value) <= 256
            and value.isascii() and value.isprintable() and not any(c.isspace() for c in value))


@dataclass(frozen=True, repr=False)
class ControlledVoiceProfile:
    account_sid: str
    api_key_sid: str
    api_key_secret: str
    twiml_app_sid: str
    shared_key_id: str
    shared_key_secret: str
    public_origin: str
    caller_number: str
    approved_destination: str

    def __post_init__(self):
        if not all(sid(value, prefix) for value, prefix in (
                (self.account_sid, 'AC'), (self.api_key_sid, 'SK'), (self.twiml_app_sid, 'AP'))):
            raise VoiceConfigurationError('Identifiants du profil téléphonique invalides.')
        if not secret(self.api_key_secret) or not secret(self.shared_key_secret):
            raise VoiceConfigurationError('Secrets du profil téléphonique invalides.')
        if not isinstance(self.shared_key_id, str) or not re.fullmatch(r'webhooks_sharedkey_[A-Za-z0-9]{26}', self.shared_key_id):
            raise VoiceConfigurationError('Identifiant de signature téléphonique invalide.')
        try:
            origin = urlsplit(self.public_origin)
            host_is_domain = False
            if origin.hostname:
                try:
                    ipaddress.ip_address(origin.hostname)
                except ValueError:
                    host_is_domain = all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                                         for label in origin.hostname.split('.'))
            valid = (host_is_domain and origin.scheme == 'https' and origin.hostname and origin.netloc == origin.hostname
                     and '.' in origin.hostname and not origin.hostname.endswith('.')
                     and re.fullmatch(r'[a-z0-9.-]+', origin.hostname)
                     and not origin.username and not origin.password and origin.port is None
                     and not origin.path and not origin.query and not origin.fragment)
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise VoiceConfigurationError('Origine HTTPS publique invalide.')
        for value in (self.caller_number, self.approved_destination):
            if not isinstance(value, str) or not re.fullmatch(r'\+[1-9][0-9]{8,14}', value):
                raise VoiceConfigurationError('Numéro du profil téléphonique invalide.')
        if self.caller_number == self.approved_destination:
            raise VoiceConfigurationError('Le destinataire doit être différent du numéro Twilio.')


def client_identity(agent_id: UUID, intent_id: UUID):
    if not isinstance(agent_id, UUID) or not isinstance(intent_id, UUID):
        raise VoiceConfigurationError('Identité téléphonique invalide.')
    return 'ut_' + agent_id.hex + '_' + intent_id.hex


def browser_token(profile: ControlledVoiceProfile, agent_id: UUID, intent_id: UUID):
    identity = client_identity(agent_id, intent_id)
    token = AccessToken(profile.account_sid, profile.api_key_sid, profile.api_key_secret,
                        identity=identity, ttl=TOKEN_TTL_SECONDS, region='us1')
    token.add_grant(VoiceGrant(outgoing_application_sid=profile.twiml_app_sid, incoming_allow=False))
    return token.to_jwt()


def webhook_url(profile: ControlledVoiceProfile, kind: str, intent_id: UUID | None = None):
    if (kind not in HOOK_KINDS or (kind in FIXED_HOOK_KINDS and intent_id is not None)
            or (kind in INTENT_HOOK_KINDS and not isinstance(intent_id, UUID))):
        raise VoiceConfigurationError('Route téléphonique invalide.')
    path = '/api/telephony/twilio/' + kind
    if kind in INTENT_HOOK_KINDS:
        path += '/' + str(intent_id)
    return profile.public_origin + path


def authenticate_webhook(profile: ControlledVoiceProfile, kind: str, intent_id: UUID | None,
                         body: bytes, content_type: str, signature: str, signing_settings: str):
    """Authenticate all form values against a configured URL, never proxy headers.

    HMAC_SHA1 SharedKey is deliberate: this SDK's official RequestValidator
    supports it. Reject legacy account-token fallback and unsupported algorithms.
    Authenticity does not replace call ownership, replay or lifecycle checks.
    """
    url = webhook_url(profile, kind, intent_id)
    if not isinstance(body, bytes) or len(body) > MAX_WEBHOOK_BYTES:
        raise VoiceWebhookError('Notification téléphonique invalide.')
    if not isinstance(content_type, str) or content_type.split(';')[0].strip().lower() != 'application/x-www-form-urlencoded':
        raise VoiceWebhookError('Format de notification téléphonique invalide.')
    if not isinstance(signature, str) or not re.fullmatch(r'[A-Za-z0-9+/]{27}=', signature):
        raise VoiceWebhookError('Signature téléphonique invalide.')
    if not isinstance(signing_settings, str) or len(signing_settings) > 256:
        raise VoiceWebhookError('Paramètres de signature téléphonique invalides.')
    try:
        pairs = [part.strip().split('=', 1) for part in signing_settings.split(',')]
        settings = dict(pairs)
        if len(pairs) != 2 or set(settings) != {'key', 'algorithm'} or settings != {
                'key': profile.shared_key_id, 'algorithm': 'HMAC_SHA1'}:
            raise ValueError
        values = parse_qsl(body.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                           encoding='utf-8', errors='strict', max_num_fields=128)
        if not values or any(len(key) > 128 or len(value) > 4096 for key, value in values):
            raise ValueError
        # Reject malformed percent escapes; urllib otherwise leaves them literal.
        if re.search(rb'%(?![0-9A-Fa-f]{2})', body):
            raise ValueError
        params = FormData(values)
        if any(len(params.getlist(key)) > 1 for key in CRITICAL_FIELDS):
            raise ValueError
        if not RequestValidator(profile.shared_key_secret).validate(url, params, signature):
            raise ValueError
        if params.get('AccountSid') != profile.account_sid or not sid(params.get('CallSid'), 'CA'):
            raise ValueError
        if kind == 'voice':
            # A TwiML Application has one fixed VoiceUrl. Authenticate the entire
            # form first, then validate its intent and SDK identity. The durable
            # gate must still check user/session/expiry and consume atomically.
            intent = UUID(params.get('Intent', ''))
            if str(intent) != params.get('Intent'):
                raise ValueError
            identity = params.get('From', '')
            if not re.fullmatch(r'client:ut_[0-9a-f]{32}_' + intent.hex, identity):
                raise ValueError
    except (ValueError, UnicodeError, TypeError):
        raise VoiceWebhookError('Notification téléphonique non authentifiée.') from None
    return params


def controlled_call_twiml(profile: ControlledVoiceProfile, intent_id: UUID):
    """Render only AFTER the durable intent gate; no client-supplied To exists."""
    response = VoiceResponse()
    dial = response.dial(caller_id=profile.caller_number, timeout=20,
                         time_limit=MAX_TEST_CALL_SECONDS, answer_on_bridge=True,
                         record='record-from-answer-dual',
                         recording_status_callback=webhook_url(profile, 'recording', intent_id),
                         recording_status_callback_method='POST',
                         recording_status_callback_event='completed',
                         action=webhook_url(profile, 'finish', intent_id), method='POST')
    dial.number(profile.approved_destination,
                status_callback=webhook_url(profile, 'status', intent_id),
                status_callback_method='POST',
                status_callback_event='initiated ringing answered completed')
    response.hangup()
    return str(response)

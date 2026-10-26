"""Use maintained password, encryption and OTP implementations."""
from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
from threading import BoundedSemaphore
from pathlib import Path
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
import pyotp

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
PASSWORD_WORKERS = BoundedSemaphore(2)
DUMMY_PASSWORD = PASSWORDS.hash(secrets.token_urlsafe(32))


def hash_password(value):
    with PASSWORD_WORKERS:
        return PASSWORDS.hash(value)
COOKIE = '__Host-ut_session'
CSRF_COOKIE = '__Host-ut_csrf'
SESSION_SECONDS = 12 * 60 * 60
IDLE_SECONDS = 30 * 60
ENROLLMENT_SECONDS = 10 * 60


def utcnow():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def new_token():
    return secrets.token_urlsafe(32)


def email_address(value):
    value = value.strip().lower()
    if len(value) > 254 or '..' in value or not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}', value):
        raise ValueError('Adresse email invalide')
    return value


def validate_password(value):
    if not 15 <= len(value) <= 128:
        raise ValueError('Le mot de passe doit contenir entre 15 et 128 caractères')
    if value.lower() in {'passwordpassword', 'password123456789', '123456789012345',
                         'qwertyuiopasdfgh', 'letmeinletmeinletmein'} or len(set(value)) < 5:
        raise ValueError('Choisissez un mot de passe moins prévisible')
    return value


def verify_password(encoded, candidate):
    try:
        with PASSWORD_WORKERS:
            return PASSWORDS.verify(encoded or DUMMY_PASSWORD, candidate)
    except (VerificationError, InvalidHashError):
        return False


def encryption_key(path):
    return Fernet(Path(path).read_bytes().strip())


def validate_origin(origin, deployment):
    parsed = urlsplit(origin)
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Invalid application origin')
    if deployment == 'managed':
        if parsed.scheme != 'https' or not parsed.hostname:
            raise ValueError('Managed identity requires an HTTPS origin')
    elif origin not in {'http://127.0.0.1:8110', 'https://localhost:18443'}:
        raise ValueError('Unexpected local identity origin')
    return origin


def otp_counter(secret, code, last_counter, now=None):
    if not re.fullmatch(r'[0-9]{6}', code):
        return None
    now = now or utcnow()
    counter = int(now.timestamp()) // 30
    otp = pyotp.TOTP(secret)
    for step in (counter - 1, counter, counter + 1):
        if step > last_counter and hmac.compare_digest(otp.generate_otp(step), code):
            return step
    return None

"""Strict private profiles bind calling modes to this application and provider."""
from dataclasses import fields
import json
import os
from pathlib import Path
import stat

from app.telephony.twilio_voice import ControlledVoiceProfile, ManualVoiceProfile


def private_bytes(path):
    fd = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                or stat.S_IMODE(info.st_mode) not in {0o400, 0o600, 0o440, 0o640}
                or (info.st_mode & 0o040 and info.st_gid != os.getegid()) or info.st_nlink != 1):
            raise ValueError('Fichier privé invalide.')
        raw = stream.read(8193)
    if len(raw) > 8192:
        raise ValueError('Fichier privé trop volumineux.')
    return raw


def load_profile():
    mode = os.environ.get('COMMUNICATIONS_MODE', '')
    if mode == 'disabled':
        return None
    if mode not in {'controlled_test', 'manual', 'webhooks_only', 'recovery_only'}:
        raise RuntimeError('Mode de téléphonie non autorisé.')
    try:
        if (os.environ.get('APP_ENV') != 'staging' or os.environ.get('DB_USER') != 'ut_staging_runtime'
                or os.environ.get('DB_NAME') != 'unlimited_talk_staging'):
            raise ValueError
        raw = private_bytes(os.environ['VOICE_TEST_PROFILE_FILE'])
        value = json.loads(raw)
        if not isinstance(value, dict) or type(value.get('version')) is not int:
            raise ValueError
        profile_type = {1: ControlledVoiceProfile, 2: ManualVoiceProfile}.get(value['version'])
        expected_mode = 'manual' if profile_type is ManualVoiceProfile else 'controlled_test'
        if (profile_type is None or value.get('mode') != expected_mode
                or set(value) != {'version', 'mode'} | {field.name for field in fields(profile_type)}
                or (mode in {'controlled_test', 'manual'} and mode != expected_mode)):
            raise ValueError
        value.pop('version')
        value.pop('mode')
        profile = profile_type(**value)
        if profile.public_origin != os.environ['APP_ORIGIN']:
            raise ValueError
        return profile
    except Exception:
        raise RuntimeError('Profil privé de téléphonie absent ou invalide.') from None

"""An explicit, bounded test profile is required before any Voice API is armed."""
from dataclasses import fields
import json
import os
from pathlib import Path
import stat

from app.telephony.twilio_voice import ControlledVoiceProfile


def load_profile():
    mode = os.environ.get('COMMUNICATIONS_MODE', '')
    if mode == 'disabled':
        return None
    if mode != 'controlled_test':
        raise RuntimeError('Mode de téléphonie non autorisé.')
    try:
        if (os.environ.get('APP_ENV') != 'staging' or os.environ.get('DB_USER') != 'ut_staging_runtime'
                or os.environ.get('DB_NAME') != 'unlimited_talk_staging'):
            raise ValueError
        path = Path(os.environ['VOICE_TEST_PROFILE_FILE'])
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                    or stat.S_IMODE(info.st_mode) not in {0o400, 0o600, 0o440, 0o640}
                    or (info.st_mode & 0o040 and info.st_gid != os.getegid()) or info.st_nlink != 1):
                raise ValueError
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {'version', 'mode'} | {field.name for field in fields(ControlledVoiceProfile)}:
            raise ValueError
        if type(value['version']) is not int or value['version'] != 1 or value['mode'] != 'controlled_test':
            raise ValueError
        value.pop('version')
        value.pop('mode')
        profile = ControlledVoiceProfile(**value)
        if profile.public_origin != os.environ['APP_ORIGIN']:
            raise ValueError
        return profile
    except Exception:
        raise RuntimeError('Profil privé de téléphonie absent ou invalide.') from None

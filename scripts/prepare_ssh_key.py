"""Validate SSH secret transport without exposing private-key contents."""
import base64
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

BEGIN = '-----BEGIN OPENSSH PRIVATE KEY-----'
END = '-----END OPENSSH PRIVATE KEY-----'


def normalize(value):
    if not value or len(value) > 32768:
        raise ValueError('Missing or oversized staging SSH key secret')
    value = value.replace('\\n', '\n').replace('\r', '').strip()
    if not value.startswith(BEGIN):
        try:
            value = base64.b64decode(''.join(value.split()), validate=True).decode('ascii')
        except (ValueError, UnicodeError):
            raise ValueError('SSH secret must contain a complete OpenSSH key or its base64 encoding') from None
        value = value.strip().replace('\r', '')
    match = re.fullmatch(re.escape(BEGIN) + r'\s+([A-Za-z0-9+/=\s]+)' + re.escape(END), value)
    if not match:
        raise ValueError('Incomplete SSH secret; copy only the key, without console prompts or code fences')
    try:
        decoded = base64.b64decode(''.join(match[1].split()), validate=True)
    except ValueError:
        raise ValueError('Invalid SSH secret encoding') from None
    if not decoded.startswith(b'openssh-key-v1\x00'):
        raise ValueError('Unexpected private key format')
    body = base64.b64encode(decoded).decode('ascii')
    return BEGIN + '\n' + '\n'.join(textwrap.wrap(body, 64)) + '\n' + END + '\n'


def prepare(path, value):
    key = normalize(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(key)
    result = subprocess.run(['ssh-keygen', '-y', '-P', '', '-f', str(path)],
                            capture_output=True, text=True)
    if result.returncode:
        Path(path).unlink()
        raise ValueError('SSH key is incomplete, encrypted or invalid; replace STAGING_SSH_KEY from the staging console')
    fingerprint = subprocess.run(['ssh-keygen', '-lf', '-'], input=result.stdout,
                                 capture_output=True, text=True, check=True)
    return fingerprint.stdout.split()[1]


if __name__ == '__main__':
    try:
        fingerprint = prepare(Path(sys.argv[1]), os.environ.get('STAGING_SSH_KEY', ''))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Error messages above never contain input or ssh-keygen stderr.
        print('Staging SSH key validation failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
    print('Staging deployment public-key fingerprint: ' + fingerprint)

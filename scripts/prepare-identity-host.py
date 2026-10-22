#!/usr/bin/env python3
"""Operator-only, idempotent staging key provisioning; never prints credentials."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import tempfile
from urllib.parse import urlsplit

root=Path('/etc/unlimited-talk-staging')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--origin',required=True)
    args=parser.parse_args()
    if os.geteuid()!=0 or not (root/'postgres-runtime.json').is_file():
        raise SystemExit('Run as the staging administrator on the configured staging host')
    origin=args.origin
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or any(c.isspace() for c in origin):
        raise SystemExit('An HTTPS origin without path or credentials is required')
    parsed.port  # Reject invalid ports too.
    config=root/'identity-config.json'
    if config.exists() and json.loads(config.read_text()).get('origin')!=origin:
        raise SystemExit('Existing origin differs; review the configuration instead of overwriting it')
    folder=root/'container-secrets';folder.mkdir(mode=0o700,exist_ok=True)
    if folder.is_symlink():
        raise SystemExit('Secret directory must not be a symlink')
    os.chown(folder,0,0);folder.chmod(0o700)
    key=folder/'identity_key'
    if key.exists():
        if key.is_symlink(): raise SystemExit('Secret file must not be a symlink')
        value=key.read_bytes().strip()
        if len(base64.b64decode(value,altchars=b'-_',validate=True))!=32:
            raise SystemExit('Existing encryption key is invalid; never replace it automatically')
    else:
        fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(base64.urlsafe_b64encode(secrets.token_bytes(32))+b'\n')
            stream.flush();os.fsync(stream.fileno())
    os.chown(key,10001,10001);key.chmod(0o400)
    with tempfile.NamedTemporaryFile(mode='w',dir=root,delete=False) as stream:
        json.dump({'origin':origin},stream);stream.write('\n')
        stream.flush();os.fsync(stream.fileno());temporary=stream.name
    os.replace(temporary,config);config.chmod(0o600)
    print('Staging identity key/configuration ready; existing key preserved; no credentials displayed.')


if __name__=='__main__': main()

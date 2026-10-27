"""Generate only missing staging credentials; never replace initialized secrets."""
import os
import base64
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1] / 'secrets'
root.mkdir(mode=0o700, exist_ok=True)
root.chmod(0o700)
for name in ('postgres_password', 'migrator_password', 'runtime_password', 'identity_key'):
    path = root / name
    if path.exists():
        continue
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
    with os.fdopen(fd, 'w') as stream:
        stream.write((base64.urlsafe_b64encode(secrets.token_bytes(32)).decode() if name=='identity_key' else secrets.token_urlsafe(48)) + '\n')
    # Compose file secrets bind-mount these files. Non-root container users need
    # read permission; the containing host directory remains private (0700).
    path.chmod(0o444)
print('Staging secret files ready; no values displayed.')

import json
for name, value in {
    'broker_password': secrets.token_hex(32),
    'spaces_config': json.dumps(dict(endpoint='http://objectstore:9000',region='us-east-1',bucket='disposable-imports',access_key_id='testing',secret_access_key='testing')),
}.items():
    path=root/name
    if not path.exists():
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o444)
        with os.fdopen(fd,'w') as stream: stream.write(value+'\n')
        path.chmod(0o444)

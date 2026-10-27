#!/usr/bin/env python3
"""Provision credentials and narrow private S3 egress; no migrations or app restart."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import re

ROOT=Path('/etc/unlimited-talk-staging')


def main():
    if os.geteuid()!=0:
        raise SystemExit('Root required on the dedicated staging host')
    config=json.loads((ROOT/'spaces-credentials.json').read_text())
    if not re.fullmatch(r'[a-z]{3}[0-9]',config['region']) or config['endpoint']!='https://'+config['region']+'.digitaloceanspaces.com':
        raise SystemExit('Unexpected staging storage endpoint')
    addresses={a[4][0] for a in socket.getaddrinfo(config['region']+'.digitaloceanspaces.com',443,type=socket.SOCK_STREAM,family=socket.AF_INET)}
    network=ipaddress.ip_network(json.loads((ROOT/'deployment-network.json').read_text())['database_cidr'])
    if not addresses or any(ipaddress.ip_address(ip) not in network for ip in addresses):
        raise SystemExit('Spaces must resolve inside the staging VPC before activation')
    directory=ROOT/'container-secrets'
    directory.mkdir(mode=0o700,exist_ok=True)
    values={'spaces_config':json.dumps(config)+'\n','broker_password':secrets.token_hex(32)+'\n'}
    for name,value in values.items():
        path=directory/name
        if path.exists():
            if name=='spaces_config' and json.loads(path.read_text())!=config:
                raise SystemExit('Existing storage credentials differ; explicit rotation required')
            continue
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
        with os.fdopen(fd,'w') as f:
            f.write(value)
        os.chown(path,10001 if name=='spaces_config' else 999,10001 if name=='spaces_config' else 999)
        # Worker UID 10001 and Redis UID 999 both need this one broker credential.
        if name=='broker_password':
            os.chmod(path,0o444)  # parent stays root-only; mounted only in broker/worker/dispatcher.
    if len(addresses)!=1:
        raise SystemExit('Expected one VPC Spaces gateway; review routing before allowing egress')
    current=(ROOT/'network.env').read_text()
    lines=[line for line in current.splitlines() if not line.startswith('STAGING_SPACES_CIDR=')]
    lines.append('STAGING_SPACES_CIDR='+sorted(addresses)[0]+'/32')
    (ROOT/'network.env').write_text('\n'.join(lines)+'\n')
    print('Import credentials provisioned; private gateway verified; no app restart or migration.')


if __name__=='__main__': main()

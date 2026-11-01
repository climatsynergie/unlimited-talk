"""Resume an existing attested release at boot without changing its call mode.

Never creates a container, pulls an image, runs a migration or originates a call.
Deployments remain exclusively owned by the attested deployment workflow.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

BASE = Path('/srv/unlimited-talk-staging')
SERVICES = ('broker', 'api', 'gateway', 'worker', 'dispatcher', 'voice-reconciler', 'voice-archiver')
APPLICATIONS = {'api', 'worker', 'dispatcher', 'voice-reconciler', 'voice-archiver'}


def run(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Existing runtime command failed')
    return result.stdout.strip()


def validate(containers, manifest, config):
    if set(containers) != set(SERVICES):
        raise ValueError('All previously deployed services must exist')
    if not re.fullmatch(r'[a-f0-9]{40}', manifest['revision']):
        raise ValueError('A complete release revision is required')
    if not re.fullmatch(r'ghcr.io/climatsynergie/unlimited-talk-api@sha256:[a-f0-9]{64}', manifest['image']):
        raise ValueError('An immutable application image is required')
    for name, row in containers.items():
        if row['Config']['Image'] != config['services'][name]['image']:
            raise ValueError('The existing container differs from its release')
        if name in APPLICATIONS:
            labels = row['Config']['Labels']
            if (row['Config']['Image'] != manifest['image']
                    or labels.get('org.opencontainers.image.revision') != manifest['revision']
                    or labels.get('io.unlimitedtalk.schema') != '0010_dialer'):
                raise ValueError('The existing application differs from its release')
    modes = [item.split('=', 1)[1] for item in containers['api']['Config']['Env']
             if item.startswith('COMMUNICATIONS_MODE=')]
    if len(modes) != 1 or modes[0] not in {'manual', 'webhooks_only'}:
        raise ValueError('Unexpected persisted calling mode')
    return modes[0]


def start_existing(containers, execute=run):
    for name in SERVICES:
        row = containers[name]
        if not row['State']['Running']:
            execute(['docker', 'start', row['Id']])


def main():
    if os.geteuid() != 0:
        raise ValueError('Root operator required')
    with open('/run/lock/unlimited-talk-staging-deploy.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = (BASE / 'current').resolve(strict=True)
        if release.parent != BASE / 'releases':
            raise ValueError('Unexpected release path')
        manifest = json.loads((release / 'deployment.json').read_text())
        if release.name != 'git-' + manifest['revision']:
            raise ValueError('Release path and manifest differ')
        command = ['docker', 'compose', '--project-directory', str(release), '--env-file',
                   str(release / '.env'), '-f', str(release / 'compose.managed.yaml')]
        config = json.loads(run([*command, 'config', '--format', 'json']))
        if config['name'] != 'unlimited-talk-staging-managed':
            raise ValueError('Unexpected application project')
        containers = {}
        for name in SERVICES:
            identifier = run([*command, 'ps', '-a', '-q', name])
            if not re.fullmatch(r'[a-f0-9]{64}', identifier):
                raise ValueError('A previously deployed container is missing')
            containers[name] = json.loads(run(['docker', 'inspect', identifier]))[0]
        mode = validate(containers, manifest, config)
        start_existing(containers)
        for _ in range(90):
            try:
                for name, before in containers.items():
                    row = json.loads(run(['docker', 'inspect', before['Id']]))[0]
                    if not row['State']['Running'] or row['State'].get('OOMKilled'):
                        raise RuntimeError('Runtime is not running')
                    if name != 'worker' and row['State'].get('Health', {}).get('Status') != 'healthy':
                        raise RuntimeError('Runtime is not healthy')
                with urllib.request.urlopen('http://127.0.0.1:8110/health/ready', timeout=8) as response:
                    health = json.load(response)
                if (health.get('revision') != manifest['revision'] or health.get('status') != 'ready'
                        or health.get('communications') != mode):
                    raise RuntimeError('Runtime mode or revision differs')
                print(json.dumps({'revision': manifest['revision'], 'calling_mode_preserved': mode,
                                  'existing_containers_reused': True, 'migrations_started': False}))
                return
            except Exception:
                time.sleep(1)
        raise RuntimeError('Existing runtime did not recover')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Runtime recovery stopped: ' + type(error).__name__)
        raise SystemExit(1)

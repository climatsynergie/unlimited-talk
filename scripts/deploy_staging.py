#!/usr/bin/env python3
"""Root-owned, forced-command staging deployer. Reads one bounded JSON request.

This file is installed by an administrator, never executed from a checkout by CI.
The deployment key cannot choose a shell command, host path or database target.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

REPOSITORY = 'climatsynergie/unlimited-talk'
REGISTRY_IMAGE = 'ghcr.io/climatsynergie/unlimited-talk-api'
ROOT = Path('/etc/unlimited-talk-staging')
BASE = Path('/srv/unlimited-talk-staging')
TEMPLATE = ROOT / 'deployment-template'


def parse_request(raw):
    if len(raw.encode()) > 16384:
        raise ValueError('Request too large')
    request = json.loads(raw)
    if not isinstance(request, dict) or set(request) != {'revision', 'image', 'registry_user', 'token'}:
        raise ValueError('Unexpected deployment request fields')
    if not all(isinstance(v, str) for v in request.values()):
        raise ValueError('Request values must be strings')
    if not re.fullmatch(r'[a-f0-9]{40}', request['revision']):
        raise ValueError('A complete commit SHA is required')
    if not re.fullmatch(re.escape(REGISTRY_IMAGE) + r'@sha256:[a-f0-9]{64}', request['image']):
        raise ValueError('Only the approved registry image by digest is allowed')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', request['registry_user']):
        raise ValueError('Invalid registry username')
    if not 20 <= len(request['token']) <= 8192 or any(c.isspace() for c in request['token']):
        raise ValueError('Invalid ephemeral registry token')
    return request


def github(path, token):
    req = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/' + path,
                                 headers={'Authorization': 'Bearer ' + token,
                                          'User-Agent': 'unlimited-talk-staging-deployer',
                                          'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def run(args, *, env=None, data=None, timeout=180):
    result = subprocess.run(args, env=env, input=data, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        # Do not echo credentials, arbitrary image output or command arguments.
        raise RuntimeError('Deployment command failed: ' + args[0] + ' ' + args[1])
    return result.stdout.strip()


def compose(release, *args, env=None, timeout=180):
    return run(['docker', 'compose', '-f', str(release / 'compose.managed.yaml'), *args],
               env=env, timeout=timeout)


def switch_current(release):
    link = BASE / ('.current-' + str(os.getpid()))
    link.symlink_to(release)
    os.replace(link, BASE / 'current')


def check_health(revision=None):
    with urllib.request.urlopen('http://127.0.0.1:8110/health/ready', timeout=8) as response:
        result = json.load(response)
    if result.get('status') != 'ready' or result.get('environment') != 'staging' or result.get('communications') != 'disabled':
        raise RuntimeError('Staging readiness check failed')
    if revision and result.get('revision') != revision:
        raise RuntimeError('Running revision differs from approved commit')
    return result


def deploy(request):
    revision, image, token = request['revision'], request['image'], request['token']
    main = github('commits/main', token)
    if main.get('sha') != revision:
        raise ValueError('Only current main can be deployed')
    runs = github('actions/workflows/ci.yml/runs?head_sha=' + revision + '&branch=main&status=success', token)
    if not any(r.get('head_sha') == revision and r.get('head_repository', {}).get('full_name') == REPOSITORY
               and r.get('conclusion') == 'success' and r.get('event') != 'pull_request'
               for r in runs.get('workflow_runs', [])):
        raise ValueError('Successful main-branch CI/publication is required')
    profile = json.loads((ROOT / 'postgres-runtime.json').read_text())
    network = json.loads((ROOT / 'deployment-network.json').read_text())
    previous = (BASE / 'current').resolve(strict=True)
    release = BASE / 'releases' / ('git-' + revision)
    with tempfile.TemporaryDirectory(prefix='staging-registry-', dir='/run') as credentials:
        env = {**os.environ, 'DOCKER_CONFIG': credentials, 'GH_TOKEN': token,
               'GH_CONFIG_DIR': credentials + '/gh', 'XDG_CACHE_HOME': credentials + '/cache'}
        run(['docker', 'login', 'ghcr.io', '--username', request['registry_user'], '--password-stdin'],
            env=env, data=token)
        run(['gh', 'attestation', 'verify', 'oci://' + image, '--repo', REPOSITORY,
             '--signer-workflow', REPOSITORY + '/.github/workflows/ci.yml',
             '--source-ref', 'refs/heads/main', '--source-digest', revision,
             '--deny-self-hosted-runners'], env=env, timeout=120)
        run(['docker', 'pull', image], env=env, timeout=300)
        labels = json.loads(run(['docker', 'image', 'inspect', image, '--format', '{{json .Config.Labels}}'], env=env))
        if labels.get('org.opencontainers.image.revision') != revision or labels.get('org.opencontainers.image.source') != 'https://github.com/' + REPOSITORY:
            raise ValueError('Image provenance labels do not match deployment request')
        release.mkdir(mode=0o750, parents=False, exist_ok=True)
        manifest = release / 'deployment.json'
        metadata = {'revision': revision, 'image': image}
        if manifest.exists() and json.loads(manifest.read_text()) != metadata:
            raise ValueError('Existing immutable release has different image metadata')
        if not manifest.exists():
            shutil.copy2(TEMPLATE / 'compose.managed.yaml', release / 'compose.managed.yaml')
            (release / 'scripts').mkdir(mode=0o755)
            shutil.copy2(TEMPLATE / 'nginx.conf', release / 'scripts/nginx.conf')
            settings = ('STAGING_IMAGE=' + image + '\nSTAGING_DB_HOST=' + profile['host'] +
                        '\nSTAGING_DB_CIDR=' + network['database_cidr'] + '\n')
            (release / '.env').write_text(settings)
            (release / '.env').chmod(0o600)
            manifest.write_text(json.dumps(metadata, indent=2) + '\n')
        config = json.loads(compose(release, 'config', '--format', 'json', env=env))
        if config['name'] != 'unlimited-talk-staging-managed' or set(config['services']) != {'api', 'migrate', 'gateway'}:
            raise ValueError('Unexpected root-owned deployment template')
        if config['services']['api']['image'] != image or config['services']['migrate']['image'] != image:
            raise ValueError('Migration and API must use the same tested image')
        # Migrations must follow expand/contract compatibility. Never downgrade
        # data automatically, including when application health checks fail.
        compose(release, 'run', '--rm', '--no-deps', 'migrate', env=env)
        switch_current(release)
        try:
            compose(release, 'up', '-d', '--no-deps', '--no-build', '--pull', 'never',
                    '--wait', '--wait-timeout', '120', 'api', 'gateway', env=env)
            check_health(revision)
        except Exception:
            switch_current(previous)
            try:
                compose(previous, 'up', '-d', '--no-deps', '--no-build', '--pull', 'never',
                        '--wait', '--wait-timeout', '120', 'api', 'gateway', env=env)
                check_health()
            except Exception:
                raise RuntimeError('Deployment failed; previous application could not be restored. Database was not downgraded.') from None
            raise RuntimeError('Deployment failed; previous application restored. Database was not downgraded.') from None
    result = {**metadata, 'status': 'ready', 'previous_release': previous.name,
              'deployed_at_epoch': int(time.time())}
    (ROOT / 'last-deployment.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise SystemExit('Only the installed forced-command deployer may run this operation')
    os.umask(0o077)
    with open('/run/lock/unlimited-talk-staging-deploy.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request = parse_request(sys.stdin.read(16385))
        result = deploy(request)
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Messages from these layers may contain server output. Keep CI output
        # bounded and omit the request/token. Details require operator inspection.
        print('Staging deployment stopped: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)

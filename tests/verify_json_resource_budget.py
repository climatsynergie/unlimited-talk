"""Bounded isolated resource experiment: no DB, network, credentials or providers.

The real app parses invalid campaign JSON within the generic Nginx body budget.
This deliberately stress-tests one disposable container, never a shared service.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import http.client
import json
import os
import select
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

API_IMAGE = os.environ.get('QA_API_IMAGE', 'unlimited-talk-qa-api:work')


def application(port):
    import uvicorn
    from app.main import app

    class NoDatabase:
        def begin(self):
            raise AssertionError('The unauthenticated parse test must never access a database')

    @asynccontextmanager
    async def isolated_lifespan(application):
        application.state.identity_origin = 'http://127.0.0.1:18018'
        application.state.engine = NoDatabase()
        application.state.voice_profile = None
        application.state.voice_calling_enabled = False
        yield

    app.router.lifespan_context = isolated_lifespan
    return uvicorn.Server(uvicorn.Config(app, host='0.0.0.0', port=port, log_level='critical', access_log=False))


def inside():
    server = application(18018)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(.025)
    assert server.started
    # All clients share one immutable payload; client buffers are not multiplied.
    payload = json.dumps({'name': 'x' * (9 * 1024 * 1024)}).encode()
    print('Real app; synthetic invalid campaign JSON bytes=' + str(len(payload)) + '; concurrent_requests=64; memory_limit=512MiB', flush=True)

    def request(_):
        connection = http.client.HTTPConnection('127.0.0.1', 18018, timeout=45)
        try:
            connection.request('POST', '/api/campaigns', body=payload, headers={
                'Origin': 'http://127.0.0.1:18018', 'Content-Type': 'application/json'})
            response = connection.getresponse()
            response.read()
            return response.status
        except (OSError, http.client.HTTPException) as error:
            return type(error).__name__
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=64) as pool:
        statuses = Counter(pool.map(request, range(64)))
    print('HTTP statuses: ' + repr(dict(statuses)), flush=True)
    server.should_exit = True
    thread.join(timeout=10)
    assert statuses == Counter({422: 64}), 'Concurrent malformed JSON did not fail safely'


def outside():
    root = Path(__file__).resolve().parents[1]
    name = 'ut-qa-json-budget-' + str(__import__('os').getpid())
    command = ['sudo', '-n', 'docker', 'run', '--name', name, '--network', 'none', '--read-only',
               '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--memory', '512m', '--cpus', '1', '--pids-limit', '100',
               '-e', 'PYTHONPATH=/app',
               '-v', str(root / 'tests') + ':/tests:ro', '-v', str(root / 'backend/app') + ':/app/app:ro',
               API_IMAGE, 'python', '/tests/verify_json_resource_budget.py', '--inner']
    try:
        result = subprocess.run(command, check=False, timeout=75)
        state = json.loads(subprocess.check_output(['sudo', '-n', 'docker', 'inspect', name, '--format', '{{json .State}}'], text=True))
        print('Container result: ' + json.dumps({'exit_code': result.returncode, 'oom_killed': state['OOMKilled']}), flush=True)
        return result.returncode
    finally:
        subprocess.run(['sudo', '-n', 'docker', 'rm', '-f', name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def gateway_experiment():
    """Keep load generation outside the app's exact production memory budget."""
    from verify_webhook_ingress import IMAGE
    root = Path(__file__).resolve().parents[1]
    name = 'ut-qa-json-gateway-' + str(__import__('os').getpid())
    network, api, gateway = name + '-net', name + '-api', name + '-edge'
    docker = ['sudo', '-n', 'docker']
    created = []
    subprocess.run([*docker, 'network', 'create', '--internal', network], check=True, stdout=subprocess.DEVNULL)
    try:
        with tempfile.TemporaryDirectory(prefix='ut-json-gateway-') as folder:
            config = Path(folder) / 'default.conf'
            source = Path(sys.argv[sys.argv.index('--config') + 1]) if '--config' in sys.argv else root / 'scripts/nginx.conf'
            config.write_text(source.read_text())
            config.chmod(0o644)
            Path(folder).chmod(0o755)
            common = ['--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges']
            subprocess.run([*docker, 'run', '-d', '--name', api, '--network', network, '--network-alias', 'api', *common,
                            '--memory', '512m', '--cpus', '1', '--pids-limit', '100', '-e', 'PYTHONPATH=/app',
                            '-v', str(root / 'tests') + ':/tests:ro', '-v', str(root / 'backend/app') + ':/app/app:ro',
                            API_IMAGE, 'python', '/tests/verify_json_resource_budget.py', '--server'],
                           check=True, stdout=subprocess.DEVNULL)
            created.append(api)
            subprocess.run([*docker, 'run', '-d', '--name', gateway, '--network', network, *common,
                            '--memory', '64m', '--pids-limit', '30',
                            '-v', str(config) + ':/etc/nginx/conf.d/default.conf:ro', '--entrypoint', 'nginx', IMAGE, '-g', 'daemon off;'],
                           check=True, stdout=subprocess.DEVNULL)
            created.append(gateway)
            networks = json.loads(subprocess.check_output([*docker, 'inspect', gateway, '--format', '{{json .NetworkSettings.Networks}}'], text=True))
            host, port = networks[network]['IPAddress'], 8080

            def request(path, body=None):
                connection = http.client.HTTPConnection(host, port, timeout=30)
                try:
                    try:
                        if body is None:
                            connection.request('GET', path)
                        else:
                            connection.putrequest('POST', path)
                            connection.putheader('Origin', 'http://127.0.0.1:18018')
                            connection.putheader('Content-Type', 'application/json')
                            connection.putheader('Content-Length', str(len(body)))
                            connection.endheaders()
                            # Honor an early edge rejection before transferring
                            # a body. Otherwise send the actual full JSON.
                            if not select.select([connection.sock], [], [], .1)[0]:
                                connection.send(body)
                    except BrokenPipeError:
                        # Nginx may reject Content-Length before reading a large
                        # body. Preserve and inspect its actual HTTP response.
                        pass
                    response = connection.getresponse()
                    response.read()
                    return response.status
                except (OSError, http.client.HTTPException) as error:
                    return type(error).__name__
                finally:
                    connection.close()

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if request('/health/live') == 200:
                    break
                time.sleep(.05)
            else:
                raise RuntimeError('Isolated gateway/app did not start')
            payload = json.dumps({'name': 'x' * (9 * 1024 * 1024)}).encode()
            print('Separated app/gateway; actual Nginx config; API memory512MiB; 64 unauthenticated requests of ' + str(len(payload)) + ' bytes', flush=True)
            with ThreadPoolExecutor(max_workers=64) as pool:
                statuses = Counter(pool.map(lambda _: request('/api/campaigns', payload), range(64)))
            state = json.loads(subprocess.check_output([*docker, 'inspect', api, '--format', '{{json .State}}'], text=True))
            edge_state = json.loads(subprocess.check_output([*docker, 'inspect', gateway, '--format', '{{json .State}}'], text=True))
            print('HTTP statuses: ' + repr(dict(statuses)), flush=True)
            print('App container state: ' + json.dumps({'exit_code': state['ExitCode'], 'oom_killed': state['OOMKilled'], 'running': state['Running']}), flush=True)
            print('Gateway container state: ' + json.dumps({'exit_code': edge_state['ExitCode'], 'oom_killed': edge_state['OOMKilled'], 'running': edge_state['Running']}), flush=True)
            assert not edge_state['OOMKilled'] and edge_state['Running'], 'Unauthenticated JSON exhausted the real gateway memory budget'
            assert not state['OOMKilled'] and state['Running'], 'Unauthenticated JSON exhausted the real API container memory budget'
            assert statuses == Counter({413: 64}), 'Every oversized request must be rejected before application parsing'
            bounded = json.dumps({'name': 'x' * (400 * 1024)}).encode()
            with ThreadPoolExecutor(max_workers=64) as pool:
                bounded_statuses = Counter(pool.map(lambda _: request('/api/campaigns', bounded), range(64)))
            print('Within-budget 400-KiB malformed JSON burst: ' + repr(dict(bounded_statuses)), flush=True)
            assert bounded_statuses == Counter({422: 64}), 'Within-budget malformed requests must fail validation safely'
            assert request('/health/live') == 200, 'API did not remain available after malformed-request burst'
            print('Separated JSON ingress resource regression: PASS', flush=True)
    finally:
        for container in reversed(created):
            subprocess.run([*docker, 'rm', '-f', container], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([*docker, 'network', 'rm', network], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    if '--inner' in sys.argv:
        inside()
    elif '--server' in sys.argv:
        application(8000).run()
    elif '--gateway' in sys.argv:
        gateway_experiment()
    else:
        raise SystemExit(outside())

"""Execute the production Nginx ingress configuration with a local fake upstream.

No application database, provider credentials, or external calls are used.
Requires the already cached production gateway image and Docker.
"""
import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import http.client
from pathlib import Path
import socket
import subprocess
import tempfile
import time


IMAGE = 'nginxinc/nginx-unprivileged:stable-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03'
ROOT = Path(__file__).resolve().parents[1]


def kinds():
    result = {}
    for node in ast.parse((ROOT / 'backend/app/telephony/twilio_voice.py').read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('FIXED_HOOK_KINDS', 'INTENT_HOOK_KINDS'):
                result[name] = ast.literal_eval(node.value.args[0])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'scripts/nginx.conf')
    args = parser.parse_args()
    failures = []
    name = 'ut-qa-security-ingress-' + str(__import__('os').getpid())
    with tempfile.TemporaryDirectory(prefix='ut-qa-ingress-') as directory:
        fixture = Path(directory) / 'default.conf'
        config = args.config.read_text().replace('http://api:8000', 'http://127.0.0.1:18001')
        config = config.replace('listen 8080;', 'listen 8080;\n    access_log /dev/stdout qa_ingress;')
        fixture.write_text("log_format qa_ingress '$status $request_uri';\n" + config +
                           '\nserver { listen 18001; location / { return 204; } }\n')
        fixture.chmod(0o644)
        # Nginx runs unprivileged and must traverse this read-only fixture mount.
        Path(directory).chmod(0o755)
        command = ['sudo', '-n', 'docker', 'run', '--rm', '-d', '--name', name,
                   '-p', '127.0.0.1::8080', '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '64m',
                   '-v', str(fixture) + ':/etc/nginx/conf.d/default.conf:ro',
                   '--entrypoint', 'nginx', IMAGE, '-g', 'daemon off;']
        subprocess.run(command, check=True, stdout=subprocess.PIPE)
        try:
            port = int(subprocess.check_output(['sudo', '-n', 'docker', 'port', name, '8080/tcp'], text=True).strip().rsplit(':', 1)[1])

            def request(method, path, body=b'a=b'):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
                try:
                    connection.request(method, path, body=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
                    response = connection.getresponse()
                    response.read()
                    return response.status
                finally:
                    connection.close()

            for _ in range(100):
                try:
                    if request('POST', '/api/health') == 204:
                        break
                except (OSError, http.client.HTTPException):
                    time.sleep(.05)
            else:
                raise RuntimeError('Gateway did not start')

            definitions = kinds()
            paths = ['/api/telephony/twilio/' + kind for kind in sorted(definitions['FIXED_HOOK_KINDS'])]
            paths += ['/api/telephony/twilio/' + kind + '/11111111-1111-1111-1111-111111111111'
                      for kind in sorted(definitions['INTENT_HOOK_KINDS'])]
            for path in paths:
                for method, expected in [('POST', 204), ('GET', 403), ('HEAD', 403), ('OPTIONS', 403)]:
                    status = request(method, path)
                    if status != expected:
                        failures.append(f'{method} {path}: expected {expected}, got {status}')
            print(f'Canonical method checks: {len(paths)} routes x 4 methods; failures={len(failures)}')

            incoming = '/api/telephony/twilio/incoming-recording/11111111-1111-1111-1111-111111111111'
            legacy = '/api/telephony/twilio/recording/11111111-1111-1111-1111-111111111111'
            for path in (incoming, legacy):
                status = request('POST', path, b'x' * 16385)
                print(f'Oversize 16385-byte webhook {path}: {status}')
                if status != 413:
                    failures.append(f'Body limit {path}: expected 413, got {status}')
            status = request('PUT', '/api/imports/11111111-1111-1111-1111-111111111111/source', b'x' * 17000)
            print(f'Ordinary CSV source 17000-byte request: {status}')
            if status != 204:
                failures.append(f'CSV source unexpectedly rejected: {status}')
            status = request('POST', '/api/campaigns', b'x' * (512 * 1024 + 1))
            print(f'Generic JSON 524289-byte request: {status}')
            if status != 413:
                failures.append(f'Generic JSON body budget: expected 413, got {status}')
            status = request('POST', '/api/campaigns', b'x' * (400 * 1024))
            print(f'Large bounded qualification JSON 409600-byte request: {status}')
            if status != 204:
                failures.append(f'Bounded qualification-sized request rejected: {status}')
            status = request('PUT', '/api/imports/11111111-1111-1111-1111-111111111111/source', b'x' * (1024 * 1024))
            print(f'CSV source 1-MiB request: {status}')
            if status != 204:
                failures.append(f'CSV source upload budget lost: {status}')

            auth_paths = ['/api/auth/' + action for action in
                          ('login', 'invitations/accept', 'password-reset', 'password', 'mfa/confirm')]
            for path in auth_paths:
                small = request('POST', path, b'{"synthetic":true}')
                oversized = request('POST', path, b'x' * 16385)
                print(f'Authentication body limit {path}: small={small}, oversized={oversized}')
                if small != 204 or oversized != 413:
                    failures.append(f'Authentication body limit {path}: expected 204/413, got {small}/{oversized}')

            started = time.monotonic()
            with socket.create_connection(('127.0.0.1', port), timeout=9) as stream:
                stream.settimeout(9)
                stream.sendall(('POST ' + incoming + ' HTTP/1.1\r\nHost: localhost\r\nContent-Length: 10\r\n\r\nx').encode())
                try:
                    header = stream.recv(2048)
                    if header:
                        status = int(header.split(b' ', 2)[1])
                    else:
                        # Nginx can close a timed-out incomplete request without
                        # sending a response. Require its actual 408 access log.
                        logs = subprocess.check_output(['sudo', '-n', 'docker', 'logs', name], stderr=subprocess.DEVNULL, text=True)
                        status = 408 if ('408 ' + incoming + '\n') in logs else 'UNEXPECTED_EOF'
                except TimeoutError:
                    status = 'TIMEOUT'
            elapsed = time.monotonic() - started
            print(f'Webhook body idle limit: status={status}, elapsed={elapsed:.2f}s (idle timeout, not absolute request deadline)')
            if status != 408 or not 4 <= elapsed <= 8:
                failures.append(f'Expected 5-second body idle timeout, got {status} after {elapsed:.2f}s')

            # Representative burst envelope: 20 agents, six lifecycle callbacks each.
            with ThreadPoolExecutor(max_workers=20) as pool:
                statuses = Counter(pool.map(lambda _: request('POST', incoming), range(120)))
            print(f'20-agent / six-callback burst: {dict(statuses)}')
            if statuses != Counter({204: 120}):
                failures.append(f'20-agent callback burst rejected: {dict(statuses)}')
            time.sleep(2.1)
            with ThreadPoolExecutor(max_workers=60) as pool:
                statuses = Counter(pool.map(lambda _: request('POST', incoming), range(600)))
            print(f'600-callback abuse burst: {dict(statuses)}')
            if not statuses[429]:
                failures.append('Webhook ingress abuse burst was not rate limited')
            if set(statuses) - {204, 429}:
                failures.append(f'Unexpected abuse-burst statuses: {dict(statuses)}')
        finally:
            subprocess.run(['sudo', '-n', 'docker', 'stop', name], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for failure in failures:
        print('FAIL:', failure)
    print(f'Ingress validation: {"FAIL" if failures else "PASS"}; {len(failures)} failure(s)')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())

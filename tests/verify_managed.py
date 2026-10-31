"""Run on the dedicated staging server, as deployment administrator."""
import json
from pathlib import Path
import subprocess
import urllib.request

root = Path(__file__).resolve().parents[1]
compose = ['docker', 'compose', '-f', str(root / 'compose.managed.yaml')]


def run(*args, data=None):
    result = subprocess.run([*compose, *args], input=data, text=True,
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


for path in ('/api/system', '/health/live', '/health/ready', '/openapi.json'):
    with urllib.request.urlopen('http://127.0.0.1:8110' + path, timeout=10) as response:
        assert response.status == 200
        assert response.headers['X-Request-ID']
        assert response.headers['Cache-Control'] == 'no-store'
        body = json.load(response)
        if path == '/health/ready':
            assert body['database'] == 'connected' and body['migration'] == '0008_recordings'
            assert body['communications'] == 'webhooks_only' and body['calling_enabled'] is False

config = json.loads(run('config', '--format', 'json'))
assert set(config['services']) == {'api', 'migrate', 'gateway','broker','worker','dispatcher','voice-reconciler','voice-archiver'}
assert set(config.get('volumes',{}))=={'broker_data'}
assert 'ports' not in config['services']['broker']
for name in ('worker','dispatcher'):
    sources={s['source'] for s in config['services'][name]['secrets']}
    assert sources=={'postgres_ca','runtime_password','broker_password'}
assert 'ports' not in config['services']['api']
assert config['services']['gateway']['ports'][0]['host_ip'] == '127.0.0.1'
assert [s['source'] for s in config['services']['api']['secrets']] == ['postgres_ca', 'runtime_password', 'identity_key','spaces_config','voice_profile']
assert [s['source'] for s in config['services']['migrate']['secrets']] == ['postgres_ca', 'migrator_password']
for service in config['services'].values():
    assert service['read_only']
    for mount in service.get('volumes', []):
        assert 'unlimited-talk-v1045' not in mount.get('source', '')
code = '''
from app.database import make_engine
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
import socket,ipaddress,os,tempfile,pathlib
engine=make_engine()
with engine.connect() as db:
    assert db.execute(text('SELECT current_database()')).scalar_one() == 'unlimited_talk_staging'
    assert db.execute(text('SELECT current_user')).scalar_one() == 'ut_staging_runtime'
    ip=db.execute(text('SELECT host(inet_server_addr())')).scalar_one()
    assert ipaddress.ip_address(ip) in ipaddress.ip_network(os.environ['DB_PRIVATE_CIDR'])
    tls=db.execute(text('SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()')).one()
    assert tls.ssl and tls.version == 'TLSv1.3'
    assert not db.execute(text("SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar_one()
    assert not db.execute(text("SELECT has_schema_privilege(current_user,'staging','CREATE')")).scalar_one()
    assert db.execute(text("SELECT value FROM staging.environment_metadata WHERE key='data_policy'")).scalar_one() == 'synthetic_only'
for statement in ["UPDATE staging.environment_metadata SET value=value", "UPDATE staging.alembic_version SET version_num=version_num", "CREATE TABLE staging.forbidden_runtime_table(id integer)", "SET ROLE ut_staging_migrator"]:
    try:
        with engine.begin() as db:
            db.execute(text(statement))
            raise AssertionError('Runtime unexpectedly allowed protected operation')
    except DBAPIError:
        pass
assert engine.pool.size() == 2
assert os.getuid() == 10001
try:
    socket.create_connection(('1.1.1.1',443),timeout=2).close()
except OSError:
    pass
else:
    raise AssertionError('Unexpected Internet egress from API')
with tempfile.TemporaryDirectory() as tmp:
    ca=pathlib.Path(tmp)/'bad-ca.crt'
    ca.write_text('-----BEGIN CERTIFICATE-----\\ninvalid\\n-----END CERTIFICATE-----\\n')
    os.environ['DB_SSLROOTCERT']=str(ca)
    invalid=make_engine()
    try:
        try:
            with invalid.connect():
                raise AssertionError('Untrusted CA accepted')
        except DBAPIError:
            pass
    finally:
        invalid.dispose()
engine.dispose()
print('Private PostgreSQL, TLS, role isolation, protected metadata, untrusted CA rejection and egress: PASS')
'''
print(run('exec', '-T', 'api', 'python', '-', data=code).strip())
print('HTTP gateway → API → managed PostgreSQL → response: PASS')

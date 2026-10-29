import os
from pathlib import Path

from sqlalchemy import URL, create_engine


def make_engine():
    # General live mode remains forbidden; an explicit bounded test requires its
    # complete private profile and the runtime role before creating any engine.
    expected = {'APP_ENV': 'staging', 'DB_NAME': 'unlimited_talk_staging'}
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Invalid staging environment')
    from app.telephony.configuration import load_profile
    load_profile()
    user = os.environ['DB_USER']
    if user not in {'ut_staging_runtime', 'ut_staging_migrator'}:
        raise RuntimeError('Unrecognized staging database role')
    host = os.environ.get('DB_HOST', '')
    deployment = os.environ.get('DB_DEPLOYMENT', 'local')
    timeout = 60000 if user == 'ut_staging_migrator' else 3000
    connection_options = {'connect_timeout': 3,
                          'options': f'-c timezone=UTC -c statement_timeout={timeout}'}
    if deployment == 'local':
        if host != 'db':
            raise RuntimeError('Local database hostname mismatch')
        port = 5432
    elif deployment == 'managed':
        if not (host.startswith('private-') and host.endswith('.d.db.ondigitalocean.com')):
            raise RuntimeError('Managed staging hostname mismatch')
        if os.environ.get('DB_SSLMODE') != 'verify-full':
            raise RuntimeError('Managed database requires verified TLS')
        ca = Path(os.environ['DB_SSLROOTCERT'])
        if not ca.is_file() or not ca.read_text().startswith('-----BEGIN CERTIFICATE-----'):
            raise RuntimeError('Database CA certificate missing or invalid')
        port = 25060
        connection_options.update(sslmode='verify-full', sslrootcert=str(ca))
    else:
        raise RuntimeError('Unknown database deployment')
    password = Path(os.environ['DB_PASSWORD_FILE']).read_text().strip()
    if len(password) < 32:
        raise RuntimeError('Invalid staging database credential')
    url = URL.create('postgresql+psycopg', username=user, password=password,
                     host=host, port=port, database='unlimited_talk_staging')
    return create_engine(url, pool_size=1 if user == 'ut_staging_migrator' else 2,
                         max_overflow=0, pool_timeout=3, pool_recycle=300,
                         pool_pre_ping=True, hide_parameters=True, connect_args=connection_options)

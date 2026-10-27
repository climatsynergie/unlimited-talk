from contextlib import asynccontextmanager
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from cryptography.fernet import InvalidToken

from app.identity.routes import router as identity_router
from app.contacts.routes import router as contacts_router
from app.identity.security import encryption_key, validate_origin
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import make_engine

logger = logging.getLogger('uvicorn.error')

# This contacts release also accepts the planned additive campaign schema.
# Deploy it before campaigns so application rollback preserves existing contacts.
COMPATIBLE_SCHEMA_REVISIONS = frozenset({'0003_contacts','0004_campaigns'})
WEB_ROOT = Path(__file__).resolve().parents[1] / 'web'
WEB_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
           "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
           "form-action 'self'; frame-ancestors 'none'")


@asynccontextmanager
async def lifespan(app):
    if not (WEB_ROOT / 'index.html').is_file():
        raise RuntimeError('Built frontend is missing')
    app.state.identity_origin = validate_origin(os.environ['APP_ORIGIN'],os.environ.get('DB_DEPLOYMENT','local'))
    app.state.identity_cipher = encryption_key(os.environ['IDENTITY_KEY_FILE'])
    app.state.engine = make_engine()
    yield
    app.state.engine.dispose()


app = FastAPI(title='Unlimited Talks — Staging', version='0.4.0', lifespan=lifespan)
app.include_router(identity_router)
app.include_router(contacts_router)
app.mount('/assets', StaticFiles(directory=WEB_ROOT / 'assets', check_dir=False), name='assets')


@app.exception_handler(StarletteHTTPException)
async def http_error(request, error):
    translations = {'Not Found': 'Ressource introuvable.',
                    'Method Not Allowed': 'Méthode non autorisée.',
                    'Unauthorized': 'Connexion requise',
                    'Forbidden': 'Accès refusé.'}
    detail = translations.get(error.detail, error.detail) if isinstance(error.detail, str) else error.detail
    return JSONResponse(status_code=error.status_code, content={'detail': detail}, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Never echo submitted passwords, invitation tokens or OTPs in error bodies.
    return JSONResponse(status_code=422,content={'detail':[
        {'loc':list(item['loc']),'type':item['type'],'msg':'Valeur invalide'}
        for item in error.errors()]})


@app.middleware('http')
async def request_metadata(request: Request, call_next):
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    response = await call_next(request)
    response.headers['X-Request-ID'] = request_id
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if request.url.path.startswith('/assets/') and response.status_code == 200 else 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    logger.info('request_id=%s method=%s path=%s status=%s duration_ms=%.1f',
                request_id, request.method, request.url.path, response.status_code,
                (time.monotonic() - started) * 1000)
    return response


@app.get('/api/system')
def root():
    return {'application': 'Unlimited Talks', 'environment': 'staging',
            'milestone': 'contacts_imports', 'communications': 'disabled',
            'business_features': 'contacts_imports', 'readiness': '/health/ready',
            'revision': os.environ.get('APP_REVISION', 'development')}


@app.get('/', include_in_schema=False)
@app.get('/connexion', include_in_schema=False)
@app.get('/invitation', include_in_schema=False)
@app.get('/reinitialisation', include_in_schema=False)
@app.get('/accueil', include_in_schema=False)
@app.get('/compte', include_in_schema=False)
@app.get('/admin/utilisateurs', include_in_schema=False)
@app.get('/admin/invitations', include_in_schema=False)
@app.get('/admin/journal', include_in_schema=False)
@app.get('/admin/contacts', include_in_schema=False)
@app.get('/admin/imports', include_in_schema=False)
def web_app():
    return FileResponse(WEB_ROOT / 'index.html', headers={
        'Content-Security-Policy': WEB_CSP, 'X-Frame-Options': 'DENY',
        'Cross-Origin-Opener-Policy': 'same-origin',
    })


@app.get('/health/live')
def live():
    return {'status': 'alive', 'environment': 'staging'}


@app.get('/health/ready')
def ready(request: Request):
    try:
        with request.app.state.engine.connect() as connection:
            version = connection.execute(text('SELECT version_num FROM staging.alembic_version')).scalar_one()
            for table in ('identity_users','identity_sessions','identity_invitations',
                          'identity_password_resets','identity_recovery_codes','identity_audit','identity_rate_limits',
                          'contacts','contact_imports','contact_import_rows','contact_history'):
                connection.execute(text('SELECT 1 FROM staging.' + table + ' LIMIT 0'))
            secret = connection.execute(text('SELECT mfa_secret FROM staging.identity_users WHERE mfa_secret IS NOT NULL LIMIT 1')).scalar_one_or_none()
            if secret:
                request.app.state.identity_cipher.decrypt(secret.encode())
            marker = connection.execute(text("SELECT value FROM staging.environment_metadata WHERE key='environment'")).scalar_one()
            if version not in COMPATIBLE_SCHEMA_REVISIONS or marker != 'staging':
                raise ValueError('Schema/environment mismatch')
    except (SQLAlchemyError, ValueError, InvalidToken):
        logger.warning('Staging database readiness failed')
        return JSONResponse(status_code=503, content={'status': 'not_ready'})
    return {'status': 'ready', 'environment': 'staging', 'database': 'connected',
            'migration': version, 'communications': 'disabled',
            'revision': os.environ.get('APP_REVISION', 'development')}

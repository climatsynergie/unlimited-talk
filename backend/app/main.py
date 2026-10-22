from contextlib import asynccontextmanager
import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from cryptography.fernet import InvalidToken

from app.identity.routes import router as identity_router
from app.identity.security import encryption_key, validate_origin
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import make_engine

logger = logging.getLogger('uvicorn.error')

# Identity endpoints require the identity schema. The preceding compatibility
# release accepts both revisions and is the supported rollback target.
COMPATIBLE_SCHEMA_REVISIONS = frozenset({'0002_identity'})


@asynccontextmanager
async def lifespan(app):
    app.state.identity_origin = validate_origin(os.environ['APP_ORIGIN'],os.environ.get('DB_DEPLOYMENT','local'))
    app.state.identity_cipher = encryption_key(os.environ['IDENTITY_KEY_FILE'])
    app.state.engine = make_engine()
    yield
    app.state.engine.dispose()


app = FastAPI(title='Unlimited Talks — Staging', version='0.2.0', lifespan=lifespan)
app.include_router(identity_router)


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
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    logger.info('request_id=%s method=%s path=%s status=%s duration_ms=%.1f',
                request_id, request.method, request.url.path, response.status_code,
                (time.monotonic() - started) * 1000)
    return response


@app.get('/')
def root():
    return {'application': 'Unlimited Talks', 'environment': 'staging',
            'milestone': 'identity_backend', 'communications': 'disabled',
            'business_features': 'not_implemented', 'readiness': '/health/ready',
            'revision': os.environ.get('APP_REVISION', 'development')}


@app.get('/health/live')
def live():
    return {'status': 'alive', 'environment': 'staging'}


@app.get('/health/ready')
def ready(request: Request):
    try:
        with request.app.state.engine.connect() as connection:
            version = connection.execute(text('SELECT version_num FROM staging.alembic_version')).scalar_one()
            for table in ('identity_users','identity_sessions','identity_invitations',
                          'identity_password_resets','identity_recovery_codes','identity_audit','identity_rate_limits'):
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

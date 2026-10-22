from contextlib import asynccontextmanager
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import make_engine

logger = logging.getLogger('uvicorn.error')


@asynccontextmanager
async def lifespan(app):
    app.state.engine = make_engine()
    yield
    app.state.engine.dispose()


app = FastAPI(title='Unlimited Talks — Staging', version='0.1.0', lifespan=lifespan)


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
            'milestone': 'foundation', 'communications': 'disabled',
            'business_features': 'not_implemented', 'readiness': '/health/ready'}


@app.get('/health/live')
def live():
    return {'status': 'alive', 'environment': 'staging'}


@app.get('/health/ready')
def ready(request: Request):
    try:
        with request.app.state.engine.connect() as connection:
            version = connection.execute(text('SELECT version_num FROM staging.alembic_version')).scalar_one()
            marker = connection.execute(text("SELECT value FROM staging.environment_metadata WHERE key='environment'")).scalar_one()
            if version != '0001_foundation' or marker != 'staging':
                raise ValueError('Schema/environment mismatch')
    except (SQLAlchemyError, ValueError):
        logger.warning('Staging database readiness failed')
        return JSONResponse(status_code=503, content={'status': 'not_ready'})
    return {'status': 'ready', 'environment': 'staging', 'database': 'connected',
            'migration': version, 'communications': 'disabled'}

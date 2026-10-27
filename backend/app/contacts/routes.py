import hashlib
import json
import uuid
from threading import BoundedSemaphore
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from botocore.exceptions import BotoCoreError, ClientError
from app.identity.routes import same_origin
from app.identity.service import query, audit
from app.contacts import service
from app.contacts.csv_input import CsvInputError, inspect_headers, suggest_mapping
from app.contacts.storage import MAX_BYTES, put_source

preview_slot = BoundedSemaphore(1)
upload_slots = BoundedSemaphore(2)

router = APIRouter(prefix='/api', tags=['Contacts'], dependencies=[Depends(same_origin)])


class Creation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: uuid.UUID
    filename: str = Field(min_length=1,max_length=200)
    encoding: Literal['utf-8-sig','cp1252'] = 'utf-8-sig'
    delimiter: Literal[',',';','\t'] | None = None


class Mapping(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mapping: dict[str,str] = Field(max_length=9)


@router.get('/contacts')
def contacts(request: Request, search: str = Query('',max_length=100), offset: int = Query(0,ge=0,le=1_000_000)):
    with request.app.state.engine.begin() as db:
        service.administrator(db,request)
        # Literal substring matching, including % and _, avoids wildcard surprises.
        rows = query(db, '''SELECT id,phone,profile,do_not_contact,non_interested,created_at,updated_at
            FROM staging.contacts WHERE strpos(lower(phone||' '||profile::text),lower(:search))>0
            ORDER BY created_at DESC,id LIMIT 51 OFFSET :offset''', search=search,offset=offset).mappings().all()
        return {'items':[dict(r) for r in rows[:50]],'has_more':len(rows)>50}


@router.get('/contacts/{identifier}/history')
def history(identifier: uuid.UUID, request: Request, before: int = Query(9223372036854775807,ge=1)):
    with request.app.state.engine.begin() as db:
        service.administrator(db,request)
        rows=query(db, '''SELECT h.*,u.display_name AS actor_name FROM staging.contact_history h
            JOIN staging.identity_users u ON u.id=h.actor_id WHERE contact_id=:id AND h.id<:before
            ORDER BY h.id DESC LIMIT 51''', id=identifier,before=before).mappings().all()
        return {'items':[dict(r) for r in rows[:50]],'has_more':len(rows)>50}


@router.post('/imports')
def create(body: Creation, request: Request):
    with request.app.state.engine.begin() as db:
        user=service.administrator(db,request)
        # The user lock serializes quota admission and repeated client requests.
        existing=query(db,'SELECT * FROM staging.contact_imports WHERE id=:id',id=body.id).mappings().first()
        if existing:
            if existing['created_by'] != user['id']:
                raise HTTPException(409,'Identifiant d’import déjà utilisé.')
            return service.public_job(existing)
        query(db,'SELECT pg_advisory_xact_lock(74192003)')
        count=query(db,"SELECT count(*) FROM staging.contact_imports WHERE created_at>now()-interval '1 day'",).scalar_one()
        if count>=30:
            raise HTTPException(429,'La limite de 30 imports par jour est atteinte.')
        query(db,'''INSERT INTO staging.contact_imports(id,created_by,filename,encoding,delimiter,source_key)
            VALUES (:id,:actor,:filename,:encoding,:delimiter,:key)''',id=body.id,actor=user['id'],
            filename=body.filename,encoding=body.encoding,delimiter=body.delimiter,key='imports/'+str(body.id)+'/source.csv')
        return service.public_job(service.job(db,body.id))


def authorize_upload(request, identifier):
    with request.app.state.engine.begin() as db:
        service.administrator(db,request)
        row=service.job(db,identifier)
        if row['status'] not in {'upload','mapping'}:
            raise HTTPException(409,'Le fichier de cet import est déjà validé.')


def store_upload(request, identifier, source):
    with request.app.state.engine.begin() as db:
        user=service.administrator(db,request)
        row=service.job(db,identifier,lock=True)
        fingerprint=hashlib.sha256(source).hexdigest()
        if row['status'] != 'upload':
            if row['source_sha256']==fingerprint:
                return service.public_job(row)
            raise HTTPException(409,'La source est immuable. Créez un nouvel import.')
        headers,delimiter=inspect_headers(source,delimiter=row['delimiter'],encoding=row['encoding'])
        put_source(row['source_key'],source)
        query(db,'''UPDATE staging.contact_imports SET source_sha256=:hash,source_bytes=:size,
            headers=CAST(:headers AS jsonb),mapping=CAST(:mapping AS jsonb),delimiter=:delimiter,
            status='mapping',updated_at=now() WHERE id=:id''',id=identifier,hash=fingerprint,size=len(source),
            headers=json.dumps(headers),mapping=json.dumps(suggest_mapping(headers)),delimiter=delimiter)
        audit(db,user['id'],'contacts.source_uploaded',identifier)
        return service.public_job(service.job(db,identifier))


@router.put('/imports/{identifier}/source')
async def upload(identifier: uuid.UUID, request: Request):
    await run_in_threadpool(authorize_upload,request,identifier)
    if not upload_slots.acquire(blocking=False):
        raise HTTPException(429,'Deux dépôts sont déjà en cours. Réessayez dans un instant.')
    try:
        source=bytearray()
        async for chunk in request.stream():
            if len(source)+len(chunk)>MAX_BYTES:
                raise HTTPException(413,'Le fichier dépasse la limite de 10 Mio.')
            source.extend(chunk)
        try:
            return await run_in_threadpool(store_upload,request,identifier,bytes(source))
        except CsvInputError as error:
            raise HTTPException(400,str(error)) from None
        except (BotoCoreError,ClientError):
            raise HTTPException(503,'Le stockage est indisponible. Réessayez le dépôt du même fichier.') from None
    finally:
        upload_slots.release()



@router.post('/imports/{identifier}/preview')
def preview(identifier: uuid.UUID, body: Mapping, request: Request):
    if not preview_slot.acquire(blocking=False):
        raise HTTPException(429,'Un aperçu est déjà en cours de validation. Réessayez dans un instant.')
    try:
        with request.app.state.engine.begin() as db:
            service.administrator(db,request)
            return service.preview(db,service.job(db,identifier,lock=True),body.mapping)
    except ValueError as error:
        raise HTTPException(400,str(error)) from None
    except (BotoCoreError,ClientError):
        raise HTTPException(503,'Le stockage est indisponible. Réessayez l’aperçu.') from None
    finally:
        preview_slot.release()


@router.post('/imports/{identifier}/confirm')
def confirm(identifier: uuid.UUID, request: Request):
    with request.app.state.engine.begin() as db:
        user=service.administrator(db,request)
        row=service.job(db,identifier,lock=True)
        if row['status'] in {'queued','running','completed'}:
            return service.public_job(row)
        if row['status']!='preview' or not row['summary'].get('valid_count'):
            raise HTTPException(409,'Validez un aperçu contenant au moins un téléphone valide.')
        query(db,"UPDATE staging.contact_imports SET status='queued',confirmed_at=now(),next_publish_at=now(),updated_at=now() WHERE id=:id",id=identifier)
        audit(db,user['id'],'contacts.import_confirmed',identifier)
        return service.public_job(service.job(db,identifier))


@router.get('/imports')
def imports(request: Request, offset: int = Query(0,ge=0,le=100000)):
    with request.app.state.engine.begin() as db:
        service.administrator(db,request,touch=False)
        rows=query(db,'SELECT * FROM staging.contact_imports ORDER BY created_at DESC,id LIMIT 21 OFFSET :offset',offset=offset).mappings().all()
        return {'items':[service.public_job(r) for r in rows[:20]],'has_more':len(rows)>20}


@router.get('/imports/{identifier}')
def detail(identifier: uuid.UUID, request: Request):
    with request.app.state.engine.begin() as db:
        service.administrator(db,request,touch=False)
        return service.public_job(service.job(db,identifier))


@router.get('/imports/{identifier}/rows')
def rows(identifier: uuid.UUID, request: Request, after: int = Query(0,ge=0), issues: bool = False):
    with request.app.state.engine.begin() as db:
        service.administrator(db,request,touch=False)
        service.job(db,identifier)
        items=query(db,'''SELECT row_number,profile,error,warnings,duplicate_in_file,outcome FROM staging.contact_import_rows
            WHERE import_id=:id AND row_number>:after AND (NOT :issues OR error IS NOT NULL OR warnings!='[]'::jsonb)
            ORDER BY row_number LIMIT 51''',id=identifier,after=after,issues=issues).mappings().all()
        return {'items':[dict(r) for r in items[:50]],'has_more':len(items)>50}

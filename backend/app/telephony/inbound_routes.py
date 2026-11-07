"""Authenticated inbound administration and manual follow-up, without routing."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field, NaiveDatetime, StrictInt, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from app.identity import service as identity
from app.identity.routes import same_origin
from app.telephony import inbound_service as service
from app.telephony.inbound_settings import Body, Create, Update
from app.scheduling_time import resolve

router = APIRouter(prefix='/api/inbound', tags=['Appels entrants'], dependencies=[Depends(same_origin)])


class Change(Body):
    request_id: UUID
    version: StrictInt = Field(ge=0)
    stage: Literal['pending','claimed','callback','handled']
    owner_id: UUID | None = None
    local_start: NaiveDatetime | None = None
    timezone: str | None = Field(default=None, max_length=80)
    utc_offset_minutes: int | None = Field(default=None, ge=-840, le=840)

    @model_validator(mode='after')
    def schedule(self):
        if self.stage=='pending' and self.owner_id is not None:
            raise ValueError('Un suivi à traiter ne possède pas de responsable.')
        if self.stage=='callback':
            if self.local_start is None or not self.timezone: raise ValueError('Date et fuseau requis')
        elif any(v is not None for v in (self.local_start,self.timezone,self.utc_offset_minutes)):
            raise ValueError('La date concerne uniquement un rappel.')
        return self


class Note(Body):
    id: UUID
    content: str = Field(min_length=1, max_length=5000)

    @field_validator('content')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('Note requise')
        return value.strip()


@router.get('/agents')
def agents(request: Request, offset: int = Query(0, ge=0, le=100000), search: str = Query('',max_length=120)):
    with request.app.state.engine.begin() as db:
        identity.admin(db, request)
        rows = identity.query(db, '''SELECT id,display_name,role FROM staging.identity_users WHERE is_active
            AND strpos(lower(display_name||' '||email),lower(:search))>0
            ORDER BY lower(display_name),id LIMIT 101 OFFSET :offset''', offset=offset,search=search.strip()).mappings().all()
        return {'items':[dict(r) for r in rows[:100]],'has_more':len(rows)>100}


@router.get('/queues')
def queues(request: Request):
    with request.app.state.engine.begin() as db:
        actor = identity.authenticate(db, request)
        rows = identity.query(db, '''SELECT q.*,(SELECT count(*) FROM staging.inbound_followups f
            WHERE f.queue_id=q.id AND f.stage<>'handled') AS open_count FROM staging.inbound_queues q
            WHERE :admin OR EXISTS(SELECT 1 FROM staging.inbound_queue_agents a WHERE a.queue_id=q.id AND a.user_id=:user AND a.is_active)
            ORDER BY lower(q.name),q.id LIMIT 200''', admin=actor['role']=='admin', user=actor['id']).mappings().all()
        from app.telephony.incoming_presence import routing_states
        states=routing_states(db,getattr(request.app.state,'voice_profile',None))
        return {'items':[dict(r,routing_active=states.get(r['id'])=='active',routing_state=states.get(r['id'],'disconnected')) for r in rows]}


@router.get('/queues/{identifier}')
def queue(identifier: UUID, request: Request):
    with request.app.state.engine.begin() as db:
        return service.queue_detail(db, identity.authenticate(db, request), identifier,getattr(request.app.state,'voice_profile',None))


@router.post('/queues', status_code=201)
def create(body: Create, request: Request):
    try:
        with request.app.state.engine.begin() as db:
            actor = identity.admin(db, request)
            return service.settings(db, actor, body.id, body, body.id)
    except IntegrityError:
        raise HTTPException(409, 'Ce nom, ce numéro ou cet identifiant de file est déjà utilisé.') from None


@router.patch('/queues/{identifier}')
def update(identifier: UUID, body: Update, request: Request):
    try:
        with request.app.state.engine.begin() as db:
            actor = identity.admin(db, request)
            return service.settings(db, actor, identifier, body, body.request_id, body.version)
    except IntegrityError:
        raise HTTPException(409, 'Cette modification entre en conflit avec une autre action. Actualisez la file.') from None


def cards(db, identifier, stage, before=None):
    cursor = None
    if before:
        cursor = identity.query(db, 'SELECT created_at FROM staging.inbound_followups WHERE id=:id AND queue_id=:queue', id=before, queue=identifier).scalar_one_or_none()
        if cursor is None: raise HTTPException(400, 'Position de pagination invalide.')
    rows = identity.query(db, service.FOLLOWUP_SELECT+''' WHERE f.queue_id=:queue AND f.stage=:stage
        AND (CAST(:before AS uuid) IS NULL OR (f.created_at,f.id)<(CAST(:time AS timestamptz),CAST(:before AS uuid)))
        ORDER BY f.created_at DESC,f.id DESC LIMIT 51''', queue=identifier, stage=stage, before=before, time=cursor).mappings().all()
    return {'items':[dict(r) for r in rows[:50]],'has_more':len(rows)>50}


@router.get('/queues/{identifier}/board')
def board(identifier: UUID, request: Request):
    with request.app.state.engine.begin() as db:
        actor = identity.authenticate(db, request)
        configured = service.queue_detail(db, actor, identifier,getattr(request.app.state,'voice_profile',None))
        counts = dict(identity.query(db, 'SELECT stage,count(*) FROM staging.inbound_followups WHERE queue_id=:id GROUP BY stage', id=identifier).all())
        return {'queue':configured,'columns':[{'stage':stage,'name':name,'count':counts.get(stage,0),**cards(db,identifier,stage)} for stage,name in service.STAGES]}


@router.get('/queues/{identifier}/followups')
def listing(identifier: UUID, request: Request, stage: Literal['pending','claimed','callback','handled'], before: UUID | None = None):
    with request.app.state.engine.begin() as db:
        service.queue(db, identity.authenticate(db, request), identifier)
        return cards(db, identifier, stage, before)


@router.get('/followups/{identifier}')
def detail(identifier: UUID, request: Request, before: int | None = Query(None, ge=1, le=9223372036854775807)):
    with request.app.state.engine.begin() as db:
        row = service.followup(db, identity.authenticate(db, request), identifier)
        events = identity.query(db, '''SELECT e.id,e.action,e.details,e.created_at,u.display_name AS actor_name
            FROM staging.inbound_followup_events e LEFT JOIN staging.identity_users u ON u.id=e.actor_id
            WHERE e.followup_id=:id AND (CAST(:before AS bigint) IS NULL OR e.id<:before) ORDER BY e.id DESC LIMIT 51''', id=identifier, before=before).mappings().all()
        return {'followup':row,'events':[dict(e,id=str(e['id'])) for e in events[:50]],'has_more':len(events)>50}


@router.get('/followups/{identifier}/calls')
def calls(identifier: UUID, request: Request, before: UUID | None = None):
    with request.app.state.engine.begin() as db:
        service.followup(db, identity.authenticate(db, request), identifier)
        cursor = None
        if before:
            cursor = identity.query(db,'SELECT created_at FROM staging.inbound_interactions WHERE id=:id AND followup_id=:followup',id=before,followup=identifier).scalar_one_or_none()
            if cursor is None: raise HTTPException(400, 'Position de pagination invalide.')
        rows = identity.query(db, '''SELECT id,caller_number,called_number,outcome,received_at,ended_at,created_at
            FROM staging.inbound_interactions WHERE followup_id=:id AND (CAST(:before AS uuid) IS NULL
            OR (created_at,id)<(CAST(:time AS timestamptz),CAST(:before AS uuid)))
            ORDER BY created_at DESC,id DESC LIMIT 51''', id=identifier, before=before, time=cursor).mappings().all()
        result=[dict(r) for r in rows[:50]]
        from app.telephony.incoming_schema import installed
        if installed(db) and result:
            from app.telephony.incoming_history import recordings
            linked=identity.query(db,'''SELECT i.id,c.id AS call_id FROM staging.inbound_interactions i JOIN staging.inbound_calls c
                ON c.account_sid=i.account_sid AND c.parent_call_sid=i.call_sid
                WHERE i.followup_id=:followup AND i.id=ANY(CAST(:ids AS uuid[]))''',followup=identifier,ids=[str(r['id']) for r in result]).mappings().all()
            ids={r['id']:r['call_id'] for r in linked};media=recordings(db,list(ids.values()))
            for row in result:
                row['recordings']=[{k:v for k,v in item.items() if k!='call_id'} for item in media if item['call_id']==ids.get(row['id'])]
        return {'items':result,'has_more':len(rows)>50}


@router.post('/followups/{identifier}')
def change(identifier: UUID, body: Change, request: Request):
    try:
        with request.app.state.engine.begin() as db:
            # Administrative reassignment shares the identity-admin lock order.
            actor = identity.admin(db,request) if body.owner_id is not None else identity.authenticate(db,request)
            due = resolve(body.local_start,body.timezone,body.utc_offset_minutes) if body.stage=='callback' else None
            return service.change_followup(db,actor,identifier,body,due)
    except IntegrityError:
        raise HTTPException(409, 'Ce suivi a été modifié par une autre action. Actualisez sa fiche.') from None


@router.post('/followups/{identifier}/notes', status_code=201)
def note(identifier: UUID, body: Note, request: Request):
    try:
        with request.app.state.engine.begin() as db:
            actor = identity.authenticate(db, request)
            service.followup(db, actor, identifier, lock=True)
            digest = service.fingerprint(body.model_dump(mode='json'))
            old = service.replay(db,'inbound_followup_events',actor,body.id,identifier,digest,'followup_id')
            if old is not None: return old
            result={'id':str(body.id)}
            service.record_event(db,identifier,'note.added',{'content':body.content,'result':result},actor=actor['id'],request_id=body.id,digest=digest)
            return result
    except IntegrityError:
        raise HTTPException(409, 'Cet identifiant de note a déjà été utilisé autrement.') from None

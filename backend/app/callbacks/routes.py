"""Schedule, reschedule and close callbacks without inventing telephone events."""
import uuid
from datetime import datetime,timezone
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query,Request
from pydantic import BaseModel,ConfigDict,Field,NaiveDatetime
from sqlalchemy.exc import IntegrityError
from app.identity.routes import same_origin
from app.identity.service import query,authenticate
from app.scheduling_time import resolve
from app.campaigns import service as campaigns
from app.callbacks import service

router=APIRouter(prefix='/api/callbacks',tags=['Callbacks'],dependencies=[Depends(same_origin)])


class Schedule(BaseModel):
    model_config=ConfigDict(extra='forbid')
    local_start:NaiveDatetime
    timezone:str=Field(min_length=1,max_length=80)
    utc_offset_minutes:int|None=Field(None,ge=-840,le=840)
    notes:str=Field('',max_length=5000)


class Create(Schedule):
    id:uuid.UUID
    campaign_id:uuid.UUID
    contact_id:uuid.UUID
    membership_version:int=Field(ge=0)


class Update(Schedule):
    version:int=Field(ge=0)
    status:Literal['scheduled','completed','cancelled']


@router.get('/priority')
def priority(request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request,touch=False)
        return {'items':service.due_candidates(db,user),'communications':'disabled'}


@router.get('')
def listing(request:Request,scope:Literal['upcoming','due','history','all']='upcoming',owner:uuid.UUID|None=None,offset:int=Query(0,ge=0,le=100000)):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request,touch=False)
        if user['role']!='admin' and owner is not None and owner!=user['id']:
            raise HTTPException(403,'Vous pouvez consulter uniquement vos propres rappels.')
        where={'upcoming':"cb.status='scheduled'",'due':"cb.status='scheduled' AND cb.due_at<=clock_timestamp()",'history':"cb.status!='scheduled'",'all':'true'}[scope]
        rows=query(db,service.SELECT+' WHERE '+where+''' AND (:admin OR cb.owner_id=:user)
            AND (CAST(:owner AS uuid) IS NULL OR cb.owner_id=:owner) ORDER BY cb.due_at '''+('DESC' if scope=='history' else 'ASC')+''',cb.id LIMIT 101 OFFSET :offset''',
            admin=user['role']=='admin',user=user['id'],owner=owner,offset=offset).mappings().all()
        return {'items':[dict(r) for r in rows[:100]],'has_more':len(rows)>100}


@router.get('/{identifier}')
def detail(identifier:uuid.UUID,request:Request,before:int|None=Query(None,ge=1,le=9223372036854775807)):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);row=service.get(db,user,identifier)
        events=query(db,'''SELECT e.id,e.action,e.details,e.created_at,u.display_name AS actor_name FROM staging.callback_events e
            JOIN staging.identity_users u ON u.id=e.actor_id WHERE callback_id=:id AND (CAST(:before AS bigint) IS NULL OR e.id<:before)
            ORDER BY e.id DESC LIMIT 51''',id=identifier,before=before).mappings().all()
        return {'callback':row,'events':[dict(e,id=str(e['id'])) for e in events[:50]],'has_more':len(events)>50}


@router.post('',status_code=201)
def create(body:Create,request:Request):
    try:
        with request.app.state.engine.begin() as db:
            user=authenticate(db,request);campaigns.access(db,user,body.campaign_id)
            due=resolve(body.local_start,body.timezone,body.utc_offset_minutes)
            digest=campaigns.fingerprint(body.model_dump(mode='json'))
            query(db,'SELECT pg_advisory_xact_lock(:key)',key=int.from_bytes(body.id.bytes[:8],'big',signed=True))
            old=query(db,'SELECT * FROM staging.callbacks WHERE id=:id',id=body.id).mappings().first()
            if old:
                if old['owner_id']!=user['id'] or old['request_hash']!=digest:
                    raise HTTPException(409,'Cet identifiant de rappel a déjà été utilisé autrement.')
                return service.get(db,user,body.id)
            if due<=datetime.now(timezone.utc):raise HTTPException(422,'Choisissez une date et une heure futures pour le rappel.')
            contact=query(db,'SELECT * FROM staging.contacts WHERE id=:id FOR UPDATE',id=body.contact_id).mappings().first()
            if contact is None:raise HTTPException(404,'Contact introuvable.')
            if contact['do_not_contact'] or contact['non_interested']:
                raise HTTPException(409,'Un administrateur doit réactiver ce contact avant de programmer un rappel.')
            card=campaigns.contact_access(db,body.campaign_id,body.contact_id)
            if card['version']!=body.membership_version:raise HTTPException(409,'Cette fiche a changé. Actualisez-la avant de programmer le rappel.')
            if query(db,"SELECT 1 FROM staging.callbacks WHERE contact_id=:id AND status='scheduled'",id=body.contact_id).first():
                raise HTTPException(409,'Ce contact possède déjà un rappel programmé. Consultez vos rappels ou contactez un administrateur.')
            stage=query(db,"SELECT id FROM staging.campaign_stages WHERE campaign_id=:id AND kind='callback' AND is_active",id=body.campaign_id).scalar_one()
            campaigns.move(db,user,body.campaign_id,body.contact_id,stage,card['version'],uuid.uuid4())
            query(db,'''INSERT INTO staging.callbacks(id,campaign_id,contact_id,owner_id,request_hash,due_at,timezone,notes)
                VALUES (:id,:campaign,:contact,:owner,:hash,:due,:zone,:notes)''',id=body.id,campaign=body.campaign_id,contact=body.contact_id,owner=user['id'],hash=digest,due=due,zone=body.timezone,notes=body.notes)
            result=service.get(db,user,body.id);service.record(db,user,body.id,'callback.created',{'after':service.snapshot(result)})
            return result
    except IntegrityError:
        raise HTTPException(409,'Un autre rappel a été programmé pour ce contact. Actualisez la liste.') from None


@router.patch('/{identifier}')
def update(identifier:uuid.UUID,body:Update,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);row=service.get(db,user,identifier)
        # Same lock order as global opt-outs and booking: campaign -> contact -> callback.
        if body.status=='scheduled':campaigns.access(db,user,row['campaign_id'])
        query(db,'SELECT id FROM staging.contacts WHERE id=:id FOR UPDATE',id=row['contact_id'])
        query(db,'SELECT id FROM staging.callbacks WHERE id=:id FOR UPDATE',id=identifier)
        row=service.get(db,user,identifier)
        if row['version']!=body.version:raise HTTPException(409,'Ce rappel a changé. Fermez puis rouvrez sa fiche avant de le modifier.')
        if row['status']!='scheduled':raise HTTPException(409,'Ce rappel est clôturé. Son historique est conservé ; programmez un nouveau rappel si nécessaire.')
        due=resolve(body.local_start,body.timezone,body.utc_offset_minutes)
        if body.status=='scheduled':
            if row['blocked_reason']:raise HTTPException(409,'Ce rappel est bloqué. Un administrateur doit rétablir les conditions d’accès, ou annuler le rappel.')
            if due!=row['due_at'] and due<=datetime.now(timezone.utc):raise HTTPException(422,'Choisissez une date et une heure futures pour reprogrammer ce rappel.')
        before=service.snapshot(row)
        query(db,'''UPDATE staging.callbacks SET due_at=:due,timezone=:zone,notes=:notes,status=:status,
            version=version+1,updated_at=clock_timestamp() WHERE id=:id''',id=identifier,due=due,zone=body.timezone,notes=body.notes,status=body.status)
        result=service.get(db,user,identifier)
        action={'scheduled':'callback.updated','completed':'callback.completed','cancelled':'callback.cancelled'}[body.status]
        service.record(db,user,identifier,action,{'before':before,'after':service.snapshot(result),'reason':'manual'})
        return result

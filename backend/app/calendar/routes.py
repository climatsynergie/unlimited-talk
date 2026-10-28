"""Shared calendar: authenticated visibility, creator/admin edits, atomic booking."""
import json
import uuid
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, NaiveDatetime, AwareDatetime, field_validator
from app.identity.routes import same_origin
from app.identity.service import query, authenticate, audit
from app.campaigns import service
from app.calendar.timezones import possibilities, resolve

router=APIRouter(prefix='/api/calendar',tags=['Calendar'],dependencies=[Depends(same_origin)])
Status=Literal['booked','completed','cancelled','no_show']


class Schedule(BaseModel):
    model_config=ConfigDict(extra='forbid')
    local_start:NaiveDatetime
    timezone:str=Field(min_length=1,max_length=80)
    utc_offset_minutes:int|None=Field(default=None,ge=-840,le=840)
    duration_minutes:int=Field(ge=5,le=1440)
    notes:str=Field(default='',max_length=5000)

    @field_validator('local_start')
    @classmethod
    def minute_precision(cls,value):
        if value.second or value.microsecond or not 2000<=value.year<=2100:
            raise ValueError('Date entre 2000 et 2100, à la minute près.')
        return value


class Booking(Schedule):
    id:uuid.UUID
    campaign_id:uuid.UUID
    contact_id:uuid.UUID
    membership_version:int=Field(ge=0)


class Update(Schedule):
    version:int=Field(ge=0)
    status:Status


SELECT='''SELECT a.*,c.phone,c.profile,ca.name AS campaign_name,u.display_name AS creator_name
    FROM staging.appointments a JOIN staging.contacts c ON c.id=a.contact_id
    JOIN staging.campaigns ca ON ca.id=a.campaign_id JOIN staging.identity_users u ON u.id=a.created_by'''


def payload(db,identifier):
    return dict(query(db,SELECT+' WHERE a.id=:id',id=identifier).mappings().one())


def record(db,user,identifier,action,details):
    query(db,'''INSERT INTO staging.appointment_events(appointment_id,actor_id,action,details)
        VALUES (:id,:actor,:action,CAST(:details AS jsonb))''',id=identifier,actor=user['id'],action=action,details=json.dumps(details,default=str))
    audit(db,user['id'],action,identifier)


@router.get('/resolve')
def local_time(request:Request,local_start:NaiveDatetime,timezone:str=Query(max_length=80)):
    with request.app.state.engine.begin() as db:
        authenticate(db,request)
        return {'options':possibilities(local_start,timezone)}


@router.get('')
def listing(request:Request,start:AwareDatetime,end:AwareDatetime,creator:uuid.UUID|None=None,status:Status|None=None,exclude_cancelled:bool=False,
            offset:int=Query(0,ge=0,le=100000)):
    if end<=start or end-start>timedelta(days=93):
        raise HTTPException(422,'Choisissez une période de 93 jours maximum.')
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request)
        rows=query(db,SELECT+''' WHERE a.starts_at>=:start - interval '24 hours' AND a.starts_at<:end AND a.ends_at>:start
            AND (CAST(:creator AS uuid) IS NULL OR a.created_by=:creator)
            AND (CAST(:status AS text) IS NULL OR a.status=:status)
            AND (NOT :exclude_cancelled OR a.status!='cancelled')
            ORDER BY a.starts_at,a.id LIMIT 101 OFFSET :offset''',start=start,end=end,creator=creator,status=status,exclude_cancelled=exclude_cancelled,offset=offset).mappings().all()
        return {'name':'Unlimited Talks','items':[dict(r) for r in rows[:100]],'has_more':len(rows)>100,'viewer_id':str(user['id'])}


@router.get('/{identifier}')
def detail(identifier:uuid.UUID,request:Request,before:int|None=Query(None,ge=1,le=9223372036854775807)):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request)
        row=query(db,SELECT+' WHERE a.id=:id',id=identifier).mappings().first()
        if row is None:raise HTTPException(404,'Rendez-vous introuvable.')
        events=query(db,'''SELECT e.id,e.action,e.details,e.created_at,u.display_name AS actor_name
            FROM staging.appointment_events e JOIN staging.identity_users u ON u.id=e.actor_id
            WHERE e.appointment_id=:id AND (CAST(:before AS bigint) IS NULL OR e.id<:before)
            ORDER BY e.id DESC LIMIT 51''',id=identifier,before=before).mappings().all()
        return {'appointment':dict(row),'can_edit':user['role']=='admin' or row['created_by']==user['id'],
                'events':[dict(e,id=str(e['id'])) for e in events[:50]],'has_more':len(events)>50}


@router.post('',status_code=201)
def create(body:Booking,request:Request):
    digest=service.fingerprint(body.model_dump(mode='json'))
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request)
        service.access(db,user,body.campaign_id)
        starts=resolve(body.local_start,body.timezone,body.utc_offset_minutes)
        query(db,'SELECT pg_advisory_xact_lock(:key)',key=int.from_bytes(body.id.bytes[:8],'big',signed=True))
        previous=query(db,'SELECT * FROM staging.appointments WHERE id=:id',id=body.id).mappings().first()
        if previous:
            if previous['created_by']!=user['id'] or previous['request_hash']!=digest:
                raise HTTPException(409,'Cet identifiant de rendez-vous a déjà été utilisé autrement.')
            return payload(db,body.id)
        contact=query(db,'SELECT * FROM staging.contacts WHERE id=:id FOR UPDATE',id=body.contact_id).mappings().first()
        if contact is None:raise HTTPException(404,'Contact introuvable.')
        if contact['do_not_contact'] or contact['non_interested']:
            raise HTTPException(409,'Un administrateur doit réactiver ce contact avant de prendre rendez-vous.')
        card=service.contact_access(db,body.campaign_id,body.contact_id)
        if card['version']!=body.membership_version:
            raise HTTPException(409,'La fiche a changé. Actualisez-la avant de prendre rendez-vous.')
        stage=query(db,"SELECT id FROM staging.campaign_stages WHERE campaign_id=:id AND kind='appointment' AND is_active",id=body.campaign_id).scalar_one()
        service.move(db,user,body.campaign_id,body.contact_id,stage,card['version'],uuid.uuid4())
        query(db,'''INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone,notes)
            VALUES (:id,:campaign,:contact,:actor,:hash,:start,:end,:zone,:notes)''',id=body.id,campaign=body.campaign_id,contact=body.contact_id,
            actor=user['id'],hash=digest,start=starts,end=starts+timedelta(minutes=body.duration_minutes),zone=body.timezone,notes=body.notes)
        result=payload(db,body.id)
        record(db,user,body.id,'appointment.created',{'after':dict(starts_at=result['starts_at'],ends_at=result['ends_at'],timezone=result['timezone'],notes=result['notes'],status=result['status'])})
        return result


@router.patch('/{identifier}')
def update(identifier:uuid.UUID,body:Update,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request)
        row=query(db,'SELECT * FROM staging.appointments WHERE id=:id FOR UPDATE',id=identifier).mappings().first()
        if row is None:raise HTTPException(404,'Rendez-vous introuvable.')
        if user['role']!='admin' and row['created_by']!=user['id']:
            raise HTTPException(403,'Seuls le créateur et les administrateurs peuvent modifier ce rendez-vous.')
        if row['version']!=body.version:
            raise HTTPException(409,'Ce rendez-vous a changé. Fermez puis rouvrez sa fiche avant de le modifier.')
        starts=resolve(body.local_start,body.timezone,body.utc_offset_minutes)
        ends=starts+timedelta(minutes=body.duration_minutes)
        fields=('starts_at','ends_at','timezone','notes','status')
        before={k:row[k] for k in fields}
        after=dict(starts_at=starts,ends_at=ends,timezone=body.timezone,notes=body.notes,status=body.status)
        query(db,'''UPDATE staging.appointments SET starts_at=:starts_at,ends_at=:ends_at,timezone=:timezone,notes=:notes,
            status=:status,version=version+1,updated_at=clock_timestamp() WHERE id=:id''',id=identifier,**after)
        record(db,user,identifier,'appointment.updated',{'before':before,'after':after})
        return payload(db,identifier)

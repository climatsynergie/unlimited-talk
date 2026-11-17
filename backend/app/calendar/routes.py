"""Shared calendar: authenticated visibility, creator/admin edits, atomic booking."""
import json
import uuid
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, NaiveDatetime, AwareDatetime, field_validator, model_validator
from app.identity.routes import same_origin
from app.identity.service import query, authenticate, audit
from app.campaigns import service
from app.scheduling_time import resolve
from app.scheduling_routes import local_time as resolve_local_time
from app.callbacks.service import cancel_for_contact
from app.qualification import Qualification, SCHEMA, complete_snapshot, contact_snapshot, save_contact_snapshot, appointment_snapshot
from app.calendar.phases import Phase, PHASE_SQL, next_phase

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
    qualification:Qualification=Field(default_factory=lambda: Qualification(schema_version=SCHEMA['schema_version'],answers={}))
    qualification_revision:str|None=Field(default=None,pattern=r'^[1-9][0-9]{0,18}$')
    source_followup_id:uuid.UUID|None=None
    source_followup_version:int|None=Field(default=None,ge=0)

    @model_validator(mode='after')
    def inbound_source(self):
        if (self.source_followup_id is None)!=(self.source_followup_version is None):
            raise ValueError('Le suivi entrant et sa version sont nécessaires ensemble.')
        return self

    @field_validator('qualification',mode='before')
    @classmethod
    def optional_qualification(cls,value):
        return {'schema_version':SCHEMA['schema_version'],'answers':{}} if value is None else value


class Update(Schedule):
    version:int=Field(ge=0)
    status:Status
    phase:Phase|None=None
    qualification:Qualification|None=None

    @model_validator(mode='after')
    def matching_phase(self):
        next_phase(self.status,self.phase)
        return self

    @field_validator('qualification')
    @classmethod
    def valid_qualification(cls,value):
        if value is not None:complete_snapshot(value)
        return value


SELECT='''SELECT a.*,'''+PHASE_SQL+''' AS phase,c.phone,c.profile,ca.name AS campaign_name,u.display_name AS creator_name
    FROM staging.appointments a JOIN staging.contacts c ON c.id=a.contact_id
    JOIN staging.campaigns ca ON ca.id=a.campaign_id JOIN staging.identity_users u ON u.id=a.created_by
    LEFT JOIN LATERAL (SELECT e.details FROM staging.appointment_events e WHERE e.appointment_id=a.id
        AND e.action IN ('appointment.created','appointment.updated') ORDER BY e.id DESC LIMIT 1) latest ON true'''


def payload(db,identifier):
    return dict(query(db,SELECT+' WHERE a.id=:id',id=identifier).mappings().one())


def record(db,user,identifier,action,details):
    query(db,'''INSERT INTO staging.appointment_events(appointment_id,actor_id,action,details)
        VALUES (:id,:actor,:action,CAST(:details AS jsonb))''',id=identifier,actor=user['id'],action=action,details=json.dumps(details,default=str))
    audit(db,user['id'],action,identifier)


@router.get('/resolve')
def local_time(request:Request,local_start:NaiveDatetime,timezone:str=Query(max_length=80)):
    return resolve_local_time(request,local_start,timezone)


@router.get('')
def listing(request:Request,start:AwareDatetime,end:AwareDatetime,creator:uuid.UUID|None=None,status:Status|None=None,phase:Phase|None=None,exclude_cancelled:bool=False,
            offset:int=Query(0,ge=0,le=100000)):
    if end<=start or end-start>timedelta(days=93):
        raise HTTPException(422,'Choisissez une période de 93 jours maximum.')
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request)
        rows=query(db,SELECT+''' WHERE a.starts_at>=:start - interval '24 hours' AND a.starts_at<:end AND a.ends_at>:start
            AND (CAST(:creator AS uuid) IS NULL OR a.created_by=:creator)
            AND (CAST(:status AS text) IS NULL OR a.status=:status)
            AND (CAST(:phase AS text) IS NULL OR ('''+PHASE_SQL+''')=:phase)
            AND (NOT :exclude_cancelled OR a.status!='cancelled')
            ORDER BY a.starts_at,a.id LIMIT 101 OFFSET :offset''',start=start,end=end,creator=creator,status=status,phase=phase,exclude_cancelled=exclude_cancelled,offset=offset).mappings().all()
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
        return {'appointment':dict(row,qualification=appointment_snapshot(db,identifier)),'qualification_schema':SCHEMA,
                'can_edit':user['role']=='admin' or row['created_by']==user['id'],
                'events':[dict(e,id=str(e['id'])) for e in events[:50]],'has_more':len(events)>50}


@router.post('',status_code=201)
def create(body:Booking,request:Request):
    # Keep the preceding client's idempotency hash unchanged for normal books.
    digest=service.fingerprint(body.model_dump(mode='json',exclude={'source_followup_id','source_followup_version'} if body.source_followup_id is None else set()))
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request)
        followup=None
        if body.source_followup_id is not None:
            from app.telephony import inbound_service, inbound_booking
            followup=inbound_service.followup(db,user,body.source_followup_id)
        service.access(db,user,body.campaign_id)
        starts=resolve(body.local_start,body.timezone,body.utc_offset_minutes)
        query(db,'SELECT pg_advisory_xact_lock(:key)',key=int.from_bytes(body.id.bytes[:8],'big',signed=True))
        previous=query(db,'SELECT * FROM staging.appointments WHERE id=:id',id=body.id).mappings().first()
        if previous:
            if previous['created_by']!=user['id'] or previous['request_hash']!=digest:
                raise HTTPException(409,'Cet identifiant de rendez-vous a déjà été utilisé autrement.')
            return dict(payload(db,body.id),qualification=appointment_snapshot(db,body.id))
        contact=query(db,'SELECT * FROM staging.contacts WHERE id=:id FOR UPDATE',id=body.contact_id).mappings().first()
        if contact is None:raise HTTPException(404,'Contact introuvable.')
        if followup is not None:
            followup=inbound_service.followup(db,user,body.source_followup_id,lock=True)
            inbound_booking.eligible_followup(followup,user)
            if followup['version']!=body.source_followup_version:
                raise HTTPException(409,'Le suivi entrant a changé. Actualisez sa fiche avant de confirmer le rendez-vous.')
        if followup is not None and contact['phone']!=followup['caller_number']:
            raise HTTPException(409,'Le contact ne correspond pas à cet appel entrant.')
        if contact['do_not_contact'] or contact['non_interested']:
            raise HTTPException(409,'Un administrateur doit réactiver ce contact avant de prendre rendez-vous.')
        card=service.contact_access(db,body.campaign_id,body.contact_id)
        if card['version']!=body.membership_version:
            raise HTTPException(409,'La fiche a changé. Actualisez-la avant de prendre rendez-vous.')
        current=contact_snapshot(db,body.campaign_id,body.contact_id)
        if (current['revision'] if current else None)!=body.qualification_revision:
            raise HTTPException(409,'La qualification a changé. Actualisez la fiche avant de confirmer ce rendez-vous.')
        qualification=complete_snapshot(body.qualification)
        if not current or current['qualification']!=qualification:
            save_contact_snapshot(db,user,body.campaign_id,body.contact_id,qualification)
        stage=query(db,"SELECT id FROM staging.campaign_stages WHERE campaign_id=:id AND kind='appointment' AND is_active",id=body.campaign_id).scalar_one()
        service.move(db,user,body.campaign_id,body.contact_id,stage,card['version'],uuid.uuid4())
        query(db,'''INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone,notes)
            VALUES (:id,:campaign,:contact,:actor,:hash,:start,:end,:zone,:notes)''',id=body.id,campaign=body.campaign_id,contact=body.contact_id,
            actor=user['id'],hash=digest,start=starts,end=starts+timedelta(minutes=body.duration_minutes),zone=body.timezone,notes=body.notes)
        cancel_for_contact(db,user,body.contact_id,'appointment.booked')
        if followup is not None:
            inbound_booking.finish(db,user,followup,body.id)
        result=payload(db,body.id)
        record(db,user,body.id,'appointment.created',{'after':dict(starts_at=result['starts_at'],ends_at=result['ends_at'],timezone=result['timezone'],notes=result['notes'],status=result['status'],qualification=qualification)})
        result['qualification']=qualification
        return result


@router.patch('/{identifier}')
def update(identifier:uuid.UUID,body:Update,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request)
        reference=query(db,'SELECT campaign_id,contact_id,created_by FROM staging.appointments WHERE id=:id',id=identifier).mappings().first()
        if reference is None:raise HTTPException(404,'Rendez-vous introuvable.')
        if user['role']!='admin' and reference['created_by']!=user['id']:
            raise HTTPException(403,'Seuls le créateur et les administrateurs peuvent modifier ce rendez-vous.')
        if body.status=='booked':
            # Re-read the appointment after campaign -> contact locks, matching
            # creation/callback ordering. An intervening cancellation must not
            # turn an ordinary edit into an unchecked reconfirmation.
            query(db,'SELECT id FROM staging.campaigns WHERE id=:id FOR SHARE',id=reference['campaign_id'])
            contact=query(db,'SELECT * FROM staging.contacts WHERE id=:id FOR UPDATE',id=reference['contact_id']).mappings().one()
        row=query(db,'SELECT * FROM staging.appointments WHERE id=:id FOR UPDATE',id=identifier).mappings().one()
        if row['version']!=body.version:
            raise HTTPException(409,'Ce rendez-vous a changé. Fermez puis rouvrez sa fiche avant de le modifier.')
        reconfirming=row['status']!='booked' and body.status=='booked'
        if reconfirming:
            service.access(db,user,row['campaign_id'])
            if contact['do_not_contact'] or contact['non_interested']:
                raise HTTPException(409,'Un administrateur doit réactiver ce contact avant de prendre rendez-vous.')
            card=service.contact_access(db,row['campaign_id'],row['contact_id'])
        starts=resolve(body.local_start,body.timezone,body.utc_offset_minutes)
        ends=starts+timedelta(minutes=body.duration_minutes)
        fields=('starts_at','ends_at','timezone','notes','status')
        before={k:row[k] for k in fields}
        before['phase']=payload(db,identifier)['phase']
        previous_qualification=appointment_snapshot(db,identifier)
        if (body.qualification is not None and previous_qualification is not None
                and body.qualification.schema_version<previous_qualification['schema_version']):
            raise HTTPException(422,'Conservez le questionnaire actuel de ce rendez-vous.')
        if previous_qualification is not None:before['qualification']=previous_qualification
        after=dict(starts_at=starts,ends_at=ends,timezone=body.timezone,notes=body.notes,status=body.status)
        after['phase']=next_phase(body.status,body.phase,before['phase'])
        if body.qualification is not None:
            after['qualification']=complete_snapshot(body.qualification)
        elif previous_qualification is not None:
            after['qualification']=previous_qualification
        if reconfirming and 'qualification' not in after:
            after['qualification']=complete_snapshot(Qualification(schema_version=SCHEMA['schema_version'],answers={}))
        if reconfirming:
            stage=query(db,"SELECT id FROM staging.campaign_stages WHERE campaign_id=:id AND kind='appointment' AND is_active",id=row['campaign_id']).scalar_one()
            service.move(db,user,row['campaign_id'],row['contact_id'],stage,card['version'],uuid.uuid4())
            cancel_for_contact(db,user,row['contact_id'],'appointment.booked')
        query(db,'''UPDATE staging.appointments SET starts_at=:starts_at,ends_at=:ends_at,timezone=:timezone,notes=:notes,
            status=:status,version=version+1,updated_at=clock_timestamp() WHERE id=:id''',id=identifier,**{k:after[k] for k in fields})
        record(db,user,identifier,'appointment.updated',{'before':before,'after':after})
        return dict(payload(db,identifier),qualification=after.get('qualification'))

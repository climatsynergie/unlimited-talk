import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, AwareDatetime, field_validator
from sqlalchemy.exc import IntegrityError
from app.identity.routes import same_origin
from app.identity.service import query, audit, authenticate
from app.campaigns import service

router=APIRouter(prefix='/api/campaigns',tags=['Campaigns'],dependencies=[Depends(same_origin)])
Color=Literal['violet','blue','amber','green','rose','slate']


class Body(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Campaign(Body):
    name:str=Field(min_length=1,max_length=120)
    description:str=Field(default='',max_length=2000)
    timezone:str=Field(default='America/Toronto',max_length=80)

    @field_validator('name')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('Nom requis')
        return value.strip()

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls,value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError): raise ValueError('Fuseau horaire invalide') from None
        return value


class Update(Campaign):
    version:int=Field(ge=0)
    is_active:StrictBool


class Stage(Body):
    name:str=Field(min_length=1,max_length=80)
    color:Color='violet'

    @field_validator('name')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('Nom requis')
        return value.strip()


class Reorder(Body):
    stage_ids:list[uuid.UUID]=Field(min_length=1,max_length=30)


class Assignment(Body):
    is_active:StrictBool


class Enroll(Body):
    request_id:uuid.UUID
    contact_ids:list[uuid.UUID]=Field(default_factory=list,max_length=500)
    import_id:uuid.UUID|None=None


class Move(Body):
    request_id:uuid.UUID
    stage_id:uuid.UUID
    version:int=Field(ge=0)


class Remove(Body):
    request_id:uuid.UUID
    version:int=Field(ge=0)


class Note(Body):
    id:uuid.UUID
    content:str=Field(min_length=1,max_length=5000)

    @field_validator('content')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('Note requise')
        return value.strip()


class Restore(Body):
    request_id:uuid.UUID
    do_not_contact:StrictBool
    non_interested:StrictBool
    confirmation:Literal['REACTIVER']
    expected_updated_at:AwareDatetime


def card_payload(row):
    payload=dict(row)
    if 'queue_position' in payload: payload['queue_position']=str(payload['queue_position'])
    return payload


@router.get('')
def listing(request:Request,archived:bool=False,offset:int=Query(0,ge=0,le=100000)):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request)
        rows=query(db,'''SELECT c.*,(SELECT count(*) FROM staging.campaign_contacts m WHERE m.campaign_id=c.id AND m.is_active) AS contact_count
            FROM staging.campaigns c WHERE (c.is_active OR :archived) AND
            (:admin OR (c.is_active AND EXISTS(SELECT 1 FROM staging.campaign_agents a WHERE a.campaign_id=c.id AND a.user_id=:user AND a.is_active)))
            ORDER BY lower(c.name),c.id LIMIT 51 OFFSET :offset''',admin=user['role']=='admin',user=user['id'],archived=archived,offset=offset).mappings().all()
        return {'items':[dict(r) for r in rows[:50]],'has_more':len(rows)>50}


@router.post('',status_code=201)
def create(body:Campaign,request:Request):
    try:
        with request.app.state.engine.begin() as db:
            user=authenticate(db,request);service.administrator(user)
            query(db,'SELECT pg_advisory_xact_lock(74192004)')
            if query(db,'SELECT count(*) FROM staging.campaigns WHERE is_active').scalar_one()>=200:
                raise HTTPException(409,'La limite de 200 campagnes actives est atteinte.')
            identifier=uuid.uuid4()
            query(db,'''INSERT INTO staging.campaigns(id,name,description,timezone,created_by)
                VALUES (:id,:name,:description,:timezone,:actor)''',id=identifier,actor=user['id'],**body.model_dump())
            for position,(name,kind,color) in enumerate(service.DEFAULT_STAGES):
                query(db,'''INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position)
                    VALUES (:id,:campaign,:name,:kind,:color,:position)''',id=uuid.uuid4(),campaign=identifier,name=name,kind=kind,color=color,position=position)
            service.event(db,user,identifier,'campaign.created',body.model_dump())
            audit(db,user['id'],'campaign.created',identifier)
            return dict(service.access(db,user,identifier))
    except IntegrityError:
        raise HTTPException(409,'Une campagne porte déjà ce nom.') from None


@router.patch('/{identifier}')
def update(identifier:uuid.UUID,body:Update,request:Request):
    try:
        with request.app.state.engine.begin() as db:
            user=authenticate(db,request);service.administrator(user)
            row=service.access(db,user,identifier,edit=True,allow_archived=True)
            if row['version']!=body.version:
                raise HTTPException(409,'Cette campagne a changé. Actualisez avant de modifier ses réglages.')
            query(db,'''UPDATE staging.campaigns SET name=:name,description=:description,timezone=:timezone,
                is_active=:is_active,version=version+1,updated_at=now() WHERE id=:id''',id=identifier,**body.model_dump(exclude={'version'}))
            service.event(db,user,identifier,'campaign.updated',body.model_dump())
            audit(db,user['id'],'campaign.updated',identifier)
            return dict(service.access(db,user,identifier,allow_archived=True))
    except IntegrityError:
        raise HTTPException(409,'Une campagne porte déjà ce nom.') from None


@router.get('/{identifier}/board')
def board(identifier:uuid.UUID,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request)
        campaign=service.access(db,user,identifier,allow_archived=True)
        columns=[dict(s) for s in service.stages(db,identifier)]
        counts={r[0]:r[1] for r in query(db,'''SELECT stage_id,count(*) FROM staging.campaign_contacts
            WHERE campaign_id=:id AND is_active GROUP BY stage_id''',id=identifier)}
        cards=query(db,'''SELECT cards.* FROM staging.campaign_stages s CROSS JOIN LATERAL (
            SELECT m.contact_id,m.stage_id,m.version,m.queue_position,c.phone,c.profile,c.do_not_contact,c.non_interested,c.updated_at AS contact_updated_at
            FROM staging.campaign_contacts m JOIN staging.contacts c ON c.id=m.contact_id
            WHERE m.campaign_id=s.campaign_id AND m.stage_id=s.id AND m.is_active
            ORDER BY m.queue_position LIMIT 20) cards WHERE s.campaign_id=:id AND s.is_active''',id=identifier).mappings().all()
        for column in columns:
            column['total']=counts.get(column['id'],0)
            column['items']=[card_payload(r) for r in cards if r['stage_id']==column['id']]
        return {'campaign':dict(campaign),'stages':columns}


@router.get('/{identifier}/cards')
def cards(identifier:uuid.UUID,stage_id:uuid.UUID,request:Request,after:int=Query(0,ge=0,le=9223372036854775807)):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.access(db,user,identifier,allow_archived=True)
        rows=query(db,'''SELECT m.contact_id,m.stage_id,m.version,m.queue_position,c.phone,c.profile,c.do_not_contact,c.non_interested,c.updated_at AS contact_updated_at
            FROM staging.campaign_contacts m JOIN staging.contacts c ON c.id=m.contact_id
            WHERE m.campaign_id=:id AND m.stage_id=:stage AND m.is_active AND m.queue_position>:after
            ORDER BY m.queue_position LIMIT 21''',id=identifier,stage=stage_id,after=after).mappings().all()
        return {'items':[card_payload(r) for r in rows[:20]],'has_more':len(rows)>20}


@router.get('/{identifier}/agents')
def agents(identifier:uuid.UUID,request:Request,offset:int=Query(0,ge=0,le=100000)):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.administrator(user);service.access(db,user,identifier,allow_archived=True)
        rows=query(db,'''SELECT u.id,u.display_name,u.email,u.is_active,coalesce(a.is_active,false) AS assigned
            FROM staging.identity_users u LEFT JOIN staging.campaign_agents a ON a.user_id=u.id AND a.campaign_id=:id
            WHERE u.role='agent' ORDER BY lower(u.display_name),u.id LIMIT 51 OFFSET :offset''',id=identifier,offset=offset).mappings().all()
        return {'items':[dict(r) for r in rows[:50]],'has_more':len(rows)>50}


@router.put('/{identifier}/agents/{user_id}')
def assign(identifier:uuid.UUID,user_id:uuid.UUID,body:Assignment,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.administrator(user);service.access(db,user,identifier,edit=True)
        target=query(db,"SELECT id FROM staging.identity_users WHERE id=:id AND role='agent' AND is_active",id=user_id).first()
        if body.is_active and not target:
            raise HTTPException(400,'Choisissez un compte agent actif.')
        if body.is_active:
            query(db,'''INSERT INTO staging.campaign_agents(campaign_id,user_id,assigned_by) VALUES (:campaign,:user,:actor)
                ON CONFLICT(campaign_id,user_id) DO UPDATE SET is_active=true,assigned_by=excluded.assigned_by,assigned_at=now()''',campaign=identifier,user=user_id,actor=user['id'])
        else:
            query(db,'UPDATE staging.campaign_agents SET is_active=false WHERE campaign_id=:campaign AND user_id=:user',campaign=identifier,user=user_id)
        service.event(db,user,identifier,'agent.assigned' if body.is_active else 'agent.unassigned',{'user_id':str(user_id)})
        audit(db,user['id'],'campaign.agent_assigned' if body.is_active else 'campaign.agent_unassigned',identifier)
        return {'assigned':body.is_active}


@router.post('/{identifier}/stages',status_code=201)
def add_stage(identifier:uuid.UUID,body:Stage,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.administrator(user);service.access(db,user,identifier,edit=True)
        if len(service.stages(db,identifier))>=30:
            raise HTTPException(409,'La limite de 30 étapes actives est atteinte.')
        if query(db,'SELECT 1 FROM staging.campaign_stages WHERE campaign_id=:id AND is_active AND lower(name)=lower(:name)',id=identifier,name=body.name).first():
            raise HTTPException(409,'Une étape active porte déjà ce nom.')
        position=query(db,'SELECT coalesce(max(position),-1)+1 FROM staging.campaign_stages WHERE campaign_id=:id',id=identifier).scalar_one()
        stage=uuid.uuid4()
        query(db,'''INSERT INTO staging.campaign_stages(id,campaign_id,name,color,kind,position)
            VALUES (:id,:campaign,:name,:color,'custom',:position)''',id=stage,campaign=identifier,position=position,**body.model_dump())
        service.event(db,user,identifier,'stage.created',{'id':str(stage),**body.model_dump()})
        audit(db,user['id'],'campaign.stage_created',identifier)
        return {'id':stage}


@router.patch('/{identifier}/stages/{stage_id}')
def rename_stage(identifier:uuid.UUID,stage_id:uuid.UUID,body:Stage,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.administrator(user);service.access(db,user,identifier,edit=True)
        if query(db,'SELECT 1 FROM staging.campaign_stages WHERE campaign_id=:campaign AND id!=:id AND is_active AND lower(name)=lower(:name)',campaign=identifier,id=stage_id,name=body.name).first():
            raise HTTPException(409,'Une étape active porte déjà ce nom.')
        row=query(db,'''UPDATE staging.campaign_stages SET name=:name,color=:color WHERE campaign_id=:campaign
            AND id=:id AND is_active RETURNING id''',id=stage_id,campaign=identifier,**body.model_dump()).first()
        if not row: raise HTTPException(404,'Étape introuvable.')
        service.event(db,user,identifier,'stage.updated',{'id':str(stage_id),**body.model_dump()})
        audit(db,user['id'],'campaign.stage_updated',identifier)
        return {'status':'updated'}


@router.put('/{identifier}/stage-order')
def reorder(identifier:uuid.UUID,body:Reorder,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.administrator(user);service.access(db,user,identifier,edit=True)
        active=service.stages(db,identifier)
        if len(set(body.stage_ids))!=len(body.stage_ids) or set(body.stage_ids)!={s['id'] for s in active}:
            raise HTTPException(409,'La liste des étapes a changé. Actualisez le pipeline.')
        # Reserve inactive positions after the active list before its atomic reorder.
        inactive=query(db,'SELECT id FROM staging.campaign_stages WHERE campaign_id=:id AND NOT is_active ORDER BY position',id=identifier).scalars().all()
        for position,stage in enumerate([*body.stage_ids,*inactive]):
            query(db,'UPDATE staging.campaign_stages SET position=:position WHERE id=:id',id=stage,position=position)
        service.event(db,user,identifier,'stages.reordered',{'stage_ids':[str(i) for i in body.stage_ids]})
        audit(db,user['id'],'campaign.stages_reordered',identifier)
        return {'status':'updated'}


@router.delete('/{identifier}/stages/{stage_id}')
def archive_stage(identifier:uuid.UUID,stage_id:uuid.UUID,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.administrator(user);service.access(db,user,identifier,edit=True)
        stage=query(db,'SELECT * FROM staging.campaign_stages WHERE id=:id AND campaign_id=:campaign AND is_active',id=stage_id,campaign=identifier).mappings().first()
        if not stage: raise HTTPException(404,'Étape introuvable.')
        if stage['kind']!='custom':raise HTTPException(409,'Les étapes liées aux résultats d’appel doivent être conservées. Vous pouvez les renommer.')
        if query(db,'SELECT 1 FROM staging.campaign_contacts WHERE campaign_id=:campaign AND stage_id=:stage AND is_active LIMIT 1',campaign=identifier,stage=stage_id).first():
            raise HTTPException(409,'Déplacez les fiches de cette étape avant de l’archiver.')
        query(db,'UPDATE staging.campaign_stages SET is_active=false WHERE id=:id',id=stage_id)
        service.event(db,user,identifier,'stage.archived',{'id':str(stage_id),'name':stage['name']})
        audit(db,user['id'],'campaign.stage_archived',identifier)
        return {'status':'archived'}


@router.post('/{identifier}/contacts')
def enroll(identifier:uuid.UUID,body:Enroll,request:Request):
    if bool(body.contact_ids)==bool(body.import_id):
        raise HTTPException(400,'Choisissez des contacts ou un import terminé.')
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.administrator(user);service.access(db,user,identifier)
        return service.enroll(db,user,identifier,body.contact_ids,body.import_id,body.request_id)


@router.post('/{identifier}/contacts/{contact_id}/move')
def move(identifier:uuid.UUID,contact_id:uuid.UUID,body:Move,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.access(db,user,identifier)
        return service.move(db,user,identifier,contact_id,body.stage_id,body.version,body.request_id)


@router.get('/{identifier}/contacts/{contact_id}')
def detail(identifier:uuid.UUID,contact_id:uuid.UUID,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.access(db,user,identifier,allow_archived=True)
        card=service.contact_access(db,identifier,contact_id)
        notes=query(db,'''SELECT n.id,n.content,n.created_at,u.display_name AS actor_name FROM staging.contact_notes n
            JOIN staging.identity_users u ON u.id=n.actor_id WHERE contact_id=:contact ORDER BY n.created_at DESC,n.id LIMIT 51''',contact=contact_id).mappings().all()
        events=query(db,'''SELECT e.id,e.action,e.details,e.created_at,u.display_name AS actor_name FROM staging.campaign_events e
            JOIN staging.identity_users u ON u.id=e.actor_id WHERE campaign_id=:campaign AND contact_id=:contact
            ORDER BY e.id DESC LIMIT 51''',campaign=identifier,contact=contact_id).mappings().all()
        return {'contact':card_payload(card),'notes':[dict(n) for n in notes[:50]],'events':[{**dict(e),'id':str(e['id'])} for e in events[:50]],'notes_has_more':len(notes)>50,'events_has_more':len(events)>50}


@router.post('/{identifier}/contacts/{contact_id}/notes',status_code=201)
def note(identifier:uuid.UUID,contact_id:uuid.UUID,body:Note,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.access(db,user,identifier);service.contact_access(db,identifier,contact_id)
        previous=query(db,'SELECT * FROM staging.contact_notes WHERE id=:id',id=body.id).mappings().first()
        if previous:
            if previous['actor_id']!=user['id'] or previous['contact_id']!=contact_id or previous['campaign_id']!=identifier or previous['content']!=body.content:
                raise HTTPException(409,'Cet identifiant de note est déjà utilisé.')
            return {'id':body.id}
        query(db,'''INSERT INTO staging.contact_notes(id,contact_id,campaign_id,actor_id,content)
            VALUES (:id,:contact,:campaign,:actor,:content)''',id=body.id,contact=contact_id,campaign=identifier,actor=user['id'],content=body.content)
        service.event(db,user,identifier,'note.added',{},contact_id)
        return {'id':body.id}


@router.post('/{identifier}/contacts/{contact_id}/restore')
def restore(identifier:uuid.UUID,contact_id:uuid.UUID,body:Restore,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.administrator(user);service.access(db,user,identifier)
        service.contact_access(db,identifier,contact_id)
        payload=dict(action='contact.restored',contact=str(contact_id),**body.model_dump(mode='json',exclude={'request_id'}))
        previous=service.replay(db,user,identifier,body.request_id,payload)
        if previous is not None:return previous
        contact=query(db,'SELECT * FROM staging.contacts WHERE id=:id FOR UPDATE',id=contact_id).mappings().one()
        if contact['updated_at']!=body.expected_updated_at:
            raise HTTPException(409,'Les restrictions du contact ont changé. Actualisez sa fiche avant de le réactiver.')
        if (body.do_not_contact and not contact['do_not_contact']) or (body.non_interested and not contact['non_interested']):
            raise HTTPException(400,'Utilisez une étape de restriction pour bloquer ce contact.')
        # Clearing restrictions never restores campaigns to an automatic call queue.
        query(db,'''UPDATE staging.contacts SET do_not_contact=:dnc,non_interested=:ni,updated_at=now() WHERE id=:id''',
            id=contact_id,dnc=body.do_not_contact,ni=body.non_interested)
        result={'do_not_contact':body.do_not_contact,'non_interested':body.non_interested,'previous_do_not_contact':contact['do_not_contact'],'previous_non_interested':contact['non_interested']}
        service.event(db,user,identifier,'contact.restored',result,contact_id,body.request_id,service.fingerprint(payload))
        audit(db,user['id'],'campaign.contact_restored',identifier)
        return result


@router.post('/{identifier}/contacts/{contact_id}/remove')
def remove(identifier:uuid.UUID,contact_id:uuid.UUID,body:Remove,request:Request):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.administrator(user);service.access(db,user,identifier)
        payload=dict(action='contact.removed',contact=str(contact_id),version=body.version)
        previous=service.replay(db,user,identifier,body.request_id,payload)
        if previous is not None:return previous
        query(db,'SELECT id FROM staging.contacts WHERE id=:id FOR UPDATE',id=contact_id)
        card=service.contact_access(db,identifier,contact_id)
        if card['version']!=body.version:raise HTTPException(409,'Cette fiche a changé. Actualisez avant de la retirer.')
        query(db,'UPDATE staging.campaign_contacts SET is_active=false,version=version+1,updated_at=now() WHERE campaign_id=:campaign AND contact_id=:contact',campaign=identifier,contact=contact_id)
        result={'removed':True}
        service.event(db,user,identifier,'contact.removed',result,contact_id,body.request_id,service.fingerprint(payload))
        return result


@router.get('/{identifier}/contacts/{contact_id}/notes')
def older_notes(identifier:uuid.UUID,contact_id:uuid.UUID,request:Request,offset:int=Query(0,ge=0,le=100000)):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.access(db,user,identifier,allow_archived=True);service.contact_access(db,identifier,contact_id)
        rows=query(db,'''SELECT n.id,n.content,n.created_at,u.display_name AS actor_name FROM staging.contact_notes n
            JOIN staging.identity_users u ON u.id=n.actor_id WHERE contact_id=:contact ORDER BY n.created_at DESC,n.id LIMIT 51 OFFSET :offset''',contact=contact_id,offset=offset).mappings().all()
        return {'items':[dict(r) for r in rows[:50]],'has_more':len(rows)>50}


@router.get('/{identifier}/contacts/{contact_id}/events')
def older_events(identifier:uuid.UUID,contact_id:uuid.UUID,request:Request,before:int=Query(9223372036854775807,ge=1,le=9223372036854775807)):
    with request.app.state.engine.begin() as db:
        user=authenticate(db,request);service.access(db,user,identifier,allow_archived=True);service.contact_access(db,identifier,contact_id)
        rows=query(db,'''SELECT e.id,e.action,e.details,e.created_at,u.display_name AS actor_name FROM staging.campaign_events e
            JOIN staging.identity_users u ON u.id=e.actor_id WHERE campaign_id=:campaign AND contact_id=:contact AND e.id<:before
            ORDER BY e.id DESC LIMIT 51''',campaign=identifier,contact=contact_id,before=before).mappings().all()
        return {'items':[{**dict(r),'id':str(r['id'])} for r in rows[:50]],'has_more':len(rows)>50}

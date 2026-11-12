"""Browser-bound progress dialler: no background PSTN calls without an agent."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import Field,StrictInt,model_validator
from app.identity import service as identity
from app.identity.routes import same_origin
from app.telephony.inbound_settings import Body
from app.telephony.twilio_voice import ManualVoiceProfile,browser_token
from app.telephony import dialer_service as dialer,service

router=APIRouter(prefix='/api/telephony/dialer',tags=['Composeur'],dependencies=[Depends(same_origin)])


class Control(Body):
    browser_id: UUID
    action: Literal['start','pause','stop','hold','release']
    campaign_id: UUID | None = None
    generation: StrictInt | None = Field(default=None,ge=1)
    hold_token: UUID | None = None
    pause_cause: Literal['sdk_call','sdk_device','sdk_setup','sdk_connect','next_request'] | None = None
    failure_code: StrictInt | None = Field(default=None,ge=0,le=99999)

    @model_validator(mode='after')
    def bounded_pause_diagnostic(self):
        if ((self.pause_cause is not None and self.action!='pause')
                or (self.failure_code is not None and self.pause_cause is None)):
            raise ValueError('Diagnostic réservé à une mise en pause.')
        return self


class Next(Body):
    id: UUID
    browser_id: UUID
    generation: StrictInt = Field(ge=1)


class Heartbeat(Body):
    browser_id: UUID
    generation: StrictInt = Field(ge=1)


def profile(request):
    configured=getattr(request.app.state,'voice_profile',None)
    if not isinstance(configured,ManualVoiceProfile) or not getattr(request.app.state,'voice_calling_enabled',False):
        raise HTTPException(503,'Les appels agents doivent être activés pour utiliser le composeur.')
    return configured


@router.get('/session')
def session(request:Request):
    with request.app.state.engine.begin() as db:
        actor=identity.authenticate(db,request,touch=False)
        row=dialer.get(db,actor)
        state=dialer.public(row)
        state['owned_session']=bool(row and row['session_hash']==actor['session_hash'])
        return {'dialer':state,'enabled':isinstance(getattr(request.app.state,'voice_profile',None),ManualVoiceProfile)
            and bool(getattr(request.app.state,'voice_calling_enabled',False))}


@router.get('/campaigns')
def campaign_list(request:Request):
    with request.app.state.engine.begin() as db:
        actor=identity.authenticate(db,request,touch=False)
        rows=identity.query(db,'''SELECT c.id,c.name,c.timezone,coalesce(s.enabled,false) AS automatic_enabled
            FROM staging.campaigns c LEFT JOIN staging.voice_campaign_settings s ON s.campaign_id=c.id
            WHERE c.is_active AND (:admin OR EXISTS(SELECT 1 FROM staging.campaign_agents ag
                WHERE ag.campaign_id=c.id AND ag.user_id=:actor AND ag.is_active)) ORDER BY lower(c.name),c.id LIMIT 1000''',
            admin=actor['role']=='admin',actor=actor['id']).mappings().all()
        return {'items':[dict(r) for r in rows]}


@router.post('/control')
def control(body:Control,request:Request):
    if body.action=='start':profile(request)
    with request.app.state.engine.begin() as db:
        actor=identity.authenticate(db,request)
        result=dialer.control(db,actor,body.browser_id,body.action,body.campaign_id,body.generation,body.hold_token)
        if body.pause_cause is not None:
            # Keep the original dialer.pause fact/count. This separate bounded
            # client claim explains SDK vs request failures without free text.
            code=str(body.failure_code) if body.failure_code is not None else 'unknown'
            identity.audit(db,actor['id'],'dialer.pause_cause.'+body.pause_cause+'.'+code,result.get('campaign_id'))
    return {'dialer':result}


@router.post('/next')
def next_call(body:Next,request:Request):
    configured=profile(request)
    with request.app.state.engine.begin() as db:
        actor=identity.authenticate(db,request,touch=False)
        budget_actor=str(actor['id'])
    identity.limited(request.app.state.engine,'dialer-next',budget_actor,
                     limit=120,seconds=60,global_limit=3000,authenticated=True)
    with request.app.state.engine.begin() as db:
        actor=identity.authenticate(db,request,touch=False)
        result=dialer.next_call(db,actor,configured,body.browser_id,body.generation,body.id)
        reserved=result.pop('reserved',None)
        if reserved:result['intent']=service.public(reserved)
        actor_id=actor['id']
    # A committed one-time intent always precedes an SDK token.
    if reserved:result['token']=browser_token(configured,actor_id,body.id)
    return result


@router.post('/heartbeat')
def heartbeat(body:Heartbeat,request:Request):
    with request.app.state.engine.begin() as db:
        actor=identity.authenticate(db,request,touch=False)
        row=dialer.get(db,actor)
        if (not row or row['browser_id']!=body.browser_id or row['session_hash']!=actor['session_hash']
                or row['generation']!=body.generation):
            raise HTTPException(409,'Le composeur a changé de session.')
        if row['mode'] in {'running','booking'} and not row['lease_alive']:
            return {'dialer':dialer.control(db,actor,body.browser_id,'pause',generation=body.generation,automatic_pause=True)}
        if row['mode'] in {'running','booking'}:
            identity.query(db,'''UPDATE staging.voice_dialer_sessions SET lease_until=clock_timestamp()+interval '90 seconds'
                WHERE actor_id=:id''',id=actor['id'])
        return {'dialer':dialer.public(row)}

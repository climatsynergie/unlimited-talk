"""Agent reception controls; provider signatures remain on separate public routes."""
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,StrictBool
from app.identity.routes import same_origin
from app.identity.service import authenticate
from app.telephony import incoming_presence as presence
from app.telephony.incoming_schema import installed
from app.telephony.twilio_voice import ManualVoiceProfile,incoming_token

router=APIRouter(prefix='/api/inbound/reception',dependencies=[Depends(same_origin)])


class Body(BaseModel):model_config=ConfigDict(extra='forbid')
class Register(Body):browser_id:UUID
class Heartbeat(Body):available:StrictBool;media_ready:StrictBool
class Choice(Body):registration_id:UUID;accept:StrictBool


def configured(request,db):
    profile=getattr(request.app.state,'voice_profile',None)
    if not installed(db) or not isinstance(profile,ManualVoiceProfile):
        raise HTTPException(409,'La réception des appels n’est pas encore disponible.')
    return profile


@router.get('')
def session(request:Request):
    with request.app.state.engine.begin() as db:
        actor=authenticate(db,request)
        return presence.session(db,actor,getattr(request.app.state,'voice_profile',None),getattr(request.app.state,'voice_calling_enabled',False))


@router.post('/register',status_code=201)
def register(body:Register,request:Request):
    with request.app.state.engine.begin() as db:
        actor=authenticate(db,request);profile=configured(request,db)
        if not getattr(request.app.state,'voice_calling_enabled',False):raise HTTPException(409,'La réception est momentanément en pause.')
        return presence.register(db,actor,profile,body.browser_id)


@router.post('/{identifier}/token')
def token(identifier:UUID,request:Request):
    with request.app.state.engine.begin() as db:
        actor=authenticate(db,request);profile=configured(request,db)
        presence.own_registration(db,actor,identifier)
        if not presence.queues(db,actor,profile):raise HTTPException(403,'Aucune ligne de réception ne vous est attribuée.')
        return {'token':incoming_token(profile,identifier),'expires_in':300}


@router.patch('/{identifier}')
def heartbeat(identifier:UUID,body:Heartbeat,request:Request):
    with request.app.state.engine.begin() as db:
        actor=authenticate(db,request);profile=configured(request,db)
        return presence.heartbeat(db,actor,profile,identifier,
            body.available and getattr(request.app.state,'voice_calling_enabled',False),body.media_ready)


@router.get('/offers/{identifier}')
def offer(identifier:UUID,request:Request):
    with request.app.state.engine.begin() as db:
        actor=authenticate(db,request);configured(request,db)
        return presence.public_offer(presence.offer(db,actor,identifier))


@router.post('/offers/{identifier}')
def choose(identifier:UUID,body:Choice,request:Request):
    with request.app.state.engine.begin() as db:
        actor=authenticate(db,request);configured(request,db)
        return presence.choose(db,actor,identifier,body.registration_id,body.accept)

"""Administrator caller-ID policy; selecting a number never changes Twilio."""
import json
from uuid import UUID,uuid4

from fastapi import APIRouter,Depends,HTTPException,Request
from app.identity import service as identity
from app.identity.routes import same_origin
from app.campaigns import service as campaigns
from app.telephony import dialer_policy as policy

router=APIRouter(prefix='/api/telephony',tags=['Numéros émetteurs'],dependencies=[Depends(same_origin)])


def snapshot(db,campaign_id):
    config=policy.settings(db,campaign_id)
    if config is None:
        return dict(version=0,enabled=False,default_number_id=None,hours=[],rules=[])
    rules=identity.query(db,'''SELECT number_id,country,prefix FROM staging.voice_region_rules
        WHERE campaign_id=:id ORDER BY country,prefix''',id=campaign_id).mappings().all()
    return dict(version=config['version'],enabled=config['enabled'],default_number_id=str(config['default_number_id']) if config['default_number_id'] else None,
        hours=config['hours'],rules=[{**r,'number_id':str(r['number_id'])} for r in rules])


@router.get('/numbers')
def numbers(request:Request):
    profile=getattr(request.app.state,'voice_profile',None)
    with request.app.state.engine.begin() as db:
        identity.admin(db,request)
        if profile is None:return dict(items=[],configured=False,sync=None)
        rows=identity.query(db,'''SELECT id,number,name,country,voice_enabled,is_present,is_active,verified_at,
            verified_at>clock_timestamp()-interval '24 hours' AS fresh
            FROM staging.voice_numbers WHERE account_sid=:account ORDER BY number,id LIMIT 2000''',account=profile.account_sid).mappings().all()
        state=identity.query(db,'''SELECT synchronized_at,requested_at,last_error_code,
            (lease_until>clock_timestamp()) AS syncing FROM staging.voice_directory_state WHERE account_sid=:account''',account=profile.account_sid).mappings().first()
        return dict(items=[dict(r) for r in rows],configured=True,sync=dict(state) if state else None)


@router.post('/numbers/synchronize',status_code=202)
def synchronize(request:Request):
    profile=getattr(request.app.state,'voice_profile',None)
    if profile is None:raise HTTPException(503,'La connexion Twilio doit être configurée.')
    with request.app.state.engine.begin() as db:
        actor=identity.admin(db,request)
        identity.query(db,'''INSERT INTO staging.voice_directory_state(account_sid) VALUES (:account)
            ON CONFLICT(account_sid) DO UPDATE SET requested_at=clock_timestamp(),next_attempt_at=clock_timestamp()''',account=profile.account_sid)
        identity.audit(db,actor['id'],'voice.numbers_sync_requested')
    return {'status':'requested'}


@router.get('/campaigns/{campaign_id}/calling')
def get_settings(campaign_id:UUID,request:Request):
    with request.app.state.engine.begin() as db:
        actor=identity.authenticate(db,request)
        campaign=campaigns.access(db,actor,campaign_id,allow_archived=True)
        return {'settings':snapshot(db,campaign_id),'timezone':campaign['timezone'],
            'attempts_per_day':2,'retry_hours':2}


@router.put('/campaigns/{campaign_id}/calling')
def save_settings(campaign_id:UUID,body:policy.CallingSettings,request:Request):
    profile=getattr(request.app.state,'voice_profile',None)
    if profile is None:raise HTTPException(503,'La connexion Twilio doit être configurée.')
    payload={'action':'calling.settings_changed',**body.model_dump(mode='json')}
    with request.app.state.engine.begin() as db:
        actor=identity.admin(db,request)
        campaigns.access(db,actor,campaign_id,edit=True)
        previous=campaigns.replay(db,actor,campaign_id,body.request_id,payload)
        if previous is not None:return {'settings':previous['after']}
        before=snapshot(db,campaign_id)
        if before['version']!=body.version:raise HTTPException(409,'Ces réglages ont changé. Actualisez la campagne.')
        for identifier in {body.default_number_id,*[r.number_id for r in body.rules]}-{None}:
            policy.number(db,profile,identifier)
        identity.query(db,'''INSERT INTO staging.voice_campaign_settings(campaign_id,enabled,default_number_id,hours,version,updated_by)
            VALUES (:campaign,:enabled,:number,CAST(:hours AS jsonb),1,:actor)
            ON CONFLICT(campaign_id) DO UPDATE SET enabled=excluded.enabled,default_number_id=excluded.default_number_id,
                hours=excluded.hours,version=voice_campaign_settings.version+1,updated_at=clock_timestamp(),updated_by=excluded.updated_by''',
            campaign=campaign_id,enabled=body.enabled,number=body.default_number_id,
            hours=json.dumps([h.model_dump() for h in body.hours]),actor=actor['id'])
        identity.query(db,'DELETE FROM staging.voice_region_rules WHERE campaign_id=:id',id=campaign_id)
        for rule in body.rules:
            identity.query(db,'''INSERT INTO staging.voice_region_rules(id,campaign_id,number_id,country,prefix)
                VALUES (:id,:campaign,:number,:country,:prefix)''',id=uuid4(),campaign=campaign_id,
                number=rule.number_id,country=rule.country,prefix=rule.prefix)
        after=snapshot(db,campaign_id)
        result={'settings':after}
        campaigns.event(db,actor,campaign_id,'calling.settings_changed',dict(before=before,after=after),
            request_id=body.request_id,request_hash=campaigns.fingerprint(payload))
        identity.audit(db,actor['id'],'calling.settings_changed',campaign_id)
        return result

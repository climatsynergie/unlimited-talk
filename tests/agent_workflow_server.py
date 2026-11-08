"""Disposable browser/API/PG fixture. Never copied into the application image."""
from contextlib import asynccontextmanager
import hashlib,hmac,json,os,urllib.request,urllib.parse
from uuid import UUID,uuid4

import uvicorn
from fastapi import HTTPException,Request
from twilio.request_validator import RequestValidator
from app.main import app,lifespan
from app.database import make_engine
from app.identity.security import new_token,digest
from app.identity.service import query
from app.campaigns.service import DEFAULT_STAGES
from app.telephony.twilio_voice import ManualVoiceProfile,client_identity,webhook_url
from app.telephony import completion

assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
assert os.environ['COMMUNICATIONS_MODE']=='disabled'
control=os.environ['QA_FIXTURE_TOKEN']
assert len(control)==64
engine=make_engine()
with engine.connect() as db:
    assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
profile=ManualVoiceProfile('AC'+uuid4().hex,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
    'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100')
scenarios={}


@asynccontextmanager
async def fixture_lifespan(application):
    async with lifespan(application):
        application.state.voice_profile=profile
        application.state.voice_calling_enabled=True
        yield
    engine.dispose()


app.router.lifespan_context=fixture_lifespan


def guard(request):
    if not hmac.compare_digest(request.headers.get('X-QA-Control',''),control):
        raise HTTPException(403,'Fixture locale uniquement.')


@app.post('/api/__qa/bootstrap',include_in_schema=False)
def bootstrap(request:Request):
    guard(request)
    actor,admin,campaign,number=uuid4(),uuid4(),uuid4(),uuid4()
    token,csrf=new_token(),new_token()
    contacts=[];stage_ids={}
    with engine.begin() as db:
        for identifier,role in [(actor,'agent'),(admin,'admin')]:
            query(db,'''INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret)
                VALUES (:id,:email,:name,:role,'synthetic_unused',:secret)''',id=identifier,email=str(identifier)+'@example.invalid',
                name='Agent QA' if role=='agent' else 'Admin QA',role=role,
                secret=app.state.identity_cipher.encrypt(b'JBSWY3DPEHPK3PXP').decode() if role=='admin' else None)
        query(db,'''INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at)
            VALUES (:token,:csrf,:actor,true,clock_timestamp()+interval '1 hour')''',token=digest(token),csrf=digest(csrf),actor=actor)
        query(db,"INSERT INTO staging.campaigns(id,name,timezone,created_by) VALUES (:id,:name,'America/Toronto',:admin)",
            id=campaign,name='Parcours agent QA '+hashlib.sha256(control.encode()).hexdigest()[:16]+' '+str(campaign)[:8],admin=admin)
        for position,(name,kind,color) in enumerate(DEFAULT_STAGES):
            identifier=uuid4();stage_ids[kind]=str(identifier)
            query(db,'''INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position)
                VALUES (:id,:campaign,:name,:kind,:color,:position)''',id=identifier,campaign=campaign,name=name,kind=kind,color=color,position=position)
        query(db,'INSERT INTO staging.campaign_agents(campaign_id,user_id,assigned_by) VALUES (:campaign,:actor,:admin)',campaign=campaign,actor=actor,admin=admin)
        query(db,'''INSERT INTO staging.voice_numbers(id,account_sid,provider_sid,number,name,country,voice_enabled,verified_at)
            VALUES (:id,:account,:sid,:number,'Ligne QA','CA',true,clock_timestamp())
            ON CONFLICT(account_sid,number) DO UPDATE SET verified_at=clock_timestamp() RETURNING id''',
            id=number,account=profile.account_sid,sid='PN'+uuid4().hex,number=profile.caller_number)
        number=query(db,'SELECT id FROM staging.voice_numbers WHERE account_sid=:account AND number=:number',account=profile.account_sid,number=profile.caller_number).scalar_one()
        query(db,'''INSERT INTO staging.voice_directory_state(account_sid,synchronized_at)
            VALUES (:account,clock_timestamp()) ON CONFLICT(account_sid) DO UPDATE SET synchronized_at=clock_timestamp(),last_error_code=NULL''',account=profile.account_sid)
        query(db,'INSERT INTO staging.voice_campaign_settings(campaign_id,enabled,default_number_id,updated_by) VALUES (:campaign,true,:number,:admin)',campaign=campaign,number=number,admin=admin)
        for offset in range(3):
            identifier=uuid4()
            for area in ('613','705','902','506','204'):
                for suffix in range(100,200):
                    phone='+1'+area+'555'+str(suffix).zfill(4)
                    if not query(db,'SELECT 1 FROM staging.contacts WHERE phone=:phone',phone=phone).first():break
                else:continue
                break
            else:raise ValueError('Synthetic phone range exhausted')
            query(db,'INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,CAST(:profile AS jsonb))',
                id=identifier,phone=phone,profile=json.dumps(dict(display_name='Client QA '+str(offset+1),city='Québec')))
            query(db,'INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id) VALUES (:campaign,:contact,:stage)',
                campaign=campaign,contact=identifier,stage=UUID(stage_ids['new']))
            contacts.append(dict(id=str(identifier),name='Client QA '+str(offset+1),phone=phone))
    scenarios[str(actor)]={'campaign':str(campaign),'contacts':contacts,'stages':stage_ids}
    return dict(token=token,csrf=csrf,actor=str(actor),**scenarios[str(actor)])


def signed(kind,identifier,params):
    fields={'AccountSid':profile.account_sid,**params}
    target=webhook_url(profile,kind,identifier)
    signature=RequestValidator(profile.shared_key_secret).compute_signature(target,fields)
    request=urllib.request.Request('http://127.0.0.1:8000'+target.removeprefix(profile.public_origin),
        data=urllib.parse.urlencode(fields).encode(),method='POST',headers={
            'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':signature,
            'X-Twilio-Webhooks-Signature-Settings':'key='+profile.shared_key_id+',algorithm=HMAC_SHA1'})
    with urllib.request.urlopen(request,timeout=10) as response:return response.read()


@app.post('/api/__qa/calls/{identifier}/{action}',include_in_schema=False)
def provider(identifier:UUID,action:str,request:Request):
    guard(request)
    with engine.connect() as db:row=query(db,'SELECT * FROM staging.voice_intents WHERE id=:id',id=identifier).mappings().one()
    assert str(row['actor_id']) in scenarios and row['account_sid']==profile.account_sid
    if action=='authorize':
        signed('voice',None,dict(CallSid='CA'+uuid4().hex,Intent=str(identifier),From='client:'+client_identity(row['actor_id'],identifier)))
    elif action=='finish':
        assert row['parent_call_sid']
        child='CA'+uuid4().hex
        signed('status',identifier,dict(CallSid=child,ParentCallSid=row['parent_call_sid'],From=row['caller_number'],To=row['destination'],CallStatus='in-progress',SequenceNumber='1'))
        signed('finish',identifier,dict(CallSid=row['parent_call_sid'],DialCallSid=child,DialCallStatus='no-answer'))
        with engine.begin() as db:query(db,"UPDATE staging.voice_completion_jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE intent_id=:id",id=identifier)
        completion.process_once(engine,profile)
    else:raise HTTPException(404,'Action de test inconnue.')
    return {'ok':True}


@app.get('/api/__qa/state/{actor}',include_in_schema=False)
def state(actor:UUID,request:Request):
    guard(request);scenario=scenarios[str(actor)]
    with engine.connect() as db:
        contacts=query(db,'''SELECT c.id,m.version,s.kind,c.non_interested,c.do_not_contact
            FROM staging.contacts c JOIN staging.campaign_contacts m ON m.contact_id=c.id
            JOIN staging.campaign_stages s ON s.id=m.stage_id WHERE m.campaign_id=:id''',id=scenario['campaign']).mappings().all()
        calls=query(db,'SELECT id,contact_id,state FROM staging.voice_intents WHERE actor_id=:id ORDER BY created_at,id',id=actor).mappings().all()
    return dict(contacts=[dict(c) for c in contacts],calls=[dict(c) for c in calls])


if __name__=='__main__':
    uvicorn.run(app,host='0.0.0.0',port=8000,log_level='warning',access_log=False)

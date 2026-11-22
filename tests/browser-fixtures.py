"""Synthetic fixtures for local/CI browser tests; refuses managed deployments."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
compose+=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
if 'db' not in config['services'] or config['services']['api']['environment']['DB_HOST']!='db':
    raise SystemExit('Browser fixtures require disposable local PostgreSQL')
payload=json.load(sys.stdin)
source='''
import json,os,uuid
import pyotp
from app.database import make_engine
from app.identity.security import encryption_key,hash_password,new_token
from app.identity.service import query,recovery_codes,audit
payload=json.loads(PAYLOAD)
engine=make_engine()
cipher=encryption_key(os.environ['IDENTITY_KEY_FILE'])
with engine.begin() as db:
    if payload['op']=='seed':
        identifier=uuid.uuid4();secret=pyotp.random_base32();password=new_token();email='browser-admin-'+uuid.uuid4().hex[:8]+'@example.invalid'
        query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret) VALUES (:id,:email,'Admin navigateur','admin',:hash,:secret)",id=identifier,email=email,hash=hash_password(password),secret=cipher.encrypt(secret.encode()).decode())
        codes=recovery_codes(db,identifier);audit(db,identifier,'test.browser_fixture',identifier)
        result={'email':email,'password':password,'factor':pyotp.TOTP(secret).now(),'codes':codes,'id':str(identifier)}
    elif payload['op']=='agent':
        identifier=uuid.uuid4();password=new_token();email='pipeline-agent-'+uuid.uuid4().hex+'@example.invalid'
        query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,:name,'agent',:hash)",id=identifier,email=email,name=payload.get('name','Agent pipeline'),hash=hash_password(password))
        result={'email':email,'password':password,'id':str(identifier)}
    elif payload['op']=='inbound_number':
        for n in range(7000,10000):
            phone='+1604555'+str(n)
            if not query(db,'SELECT 1 FROM staging.inbound_queues WHERE phone=:phone',phone=phone).first():break
        else: raise ValueError('Synthetic numbers exhausted')
        result={'phone':phone}
    elif payload['op']=='inbound_call':
        from datetime import datetime,timedelta,timezone
        from app.telephony.inbound_service import record_missed
        now=datetime.now(timezone.utc)
        queue=query(db,'SELECT phone FROM staging.inbound_queues WHERE id=:id',id=payload['queue_id']).scalar_one()
        identifier=record_missed(db,queue_id=uuid.UUID(payload['queue_id']),account_sid='AC'+'a'*32,call_sid='CA'+uuid.uuid4().hex,
            caller_number=payload.get('phone'),called_number=queue,outcome='missed',received_at=now-timedelta(seconds=30),ended_at=now)
        result={'id':str(identifier)}
    elif payload['op']=='conversation_agenda':
        assert os.environ.get('COMMUNICATIONS_MODE')=='disabled'
        assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
        actor=uuid.UUID(payload['actor'])
        assert query(db,"SELECT 1 FROM staging.identity_users WHERE id=:id AND email LIKE 'browser-admin-%@example.invalid'",id=actor).first()
        from app.campaigns.service import DEFAULT_STAGES,enroll
        campaign=uuid.uuid4()
        query(db,"INSERT INTO staging.campaigns(id,name,timezone,created_by) VALUES (:id,:name,'America/Toronto',:actor)",id=campaign,name='QA export '+campaign.hex,actor=actor)
        for pos,(name,kind,color) in enumerate(DEFAULT_STAGES):
            query(db,'INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position) VALUES (:id,:campaign,:name,:kind,:color,:pos)',id=uuid.uuid4(),campaign=campaign,name=name,kind=kind,color=color,pos=pos)
        contacts=[]
        for duration in [15,21,31]:
            contact=uuid.uuid4();intent=uuid.uuid4();parent='CA'+uuid.uuid4().hex
            phone='+1907'+str(1000000+uuid.uuid4().int%8000000)
            query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,CAST(:profile AS jsonb))",id=contact,phone=phone,profile=json.dumps({'display_name':f'Démo {duration} secondes','address':'10 Rue fictive'}))
            enroll(db,{'id':actor},campaign,[contact],None,uuid.uuid4())
            query(db,"""INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,caller_number,destination,state,parent_call_sid,created_at,expires_at,consumed_at,finished_at,outcome,contact_id,campaign_id)
                VALUES (:id,:actor,repeat('a',64),repeat('b',64),'AC'||repeat('a',32),'AP'||repeat('b',32),'+14165550100',:phone,'finished',:parent,now(),now()+interval '2 minutes',now(),now(),'completed',:contact,:campaign)""",id=intent,actor=actor,phone=phone,parent=parent,contact=contact,campaign=campaign)
            query(db,"INSERT INTO staging.voice_recordings(sid,intent_id,call_sid,duration,channels) VALUES (:sid,:intent,:parent,:duration,2)",sid='RE'+uuid.uuid4().hex,intent=intent,parent=parent,duration=duration)
            contacts.append(contact)
        appt=uuid.uuid4()
        query(db,"""INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone,notes)
            VALUES (:id,:campaign,:contact,:actor,:hash,'2026-11-20T00:00:00Z','2026-11-20T00:30:00Z','America/Toronto','Notes réelles de démonstration QA')""",id=appt,campaign=campaign,contact=contacts[-1],actor=actor,hash=appt.hex)
        query(db,"INSERT INTO staging.appointment_events(appointment_id,actor_id,action,details) VALUES (:id,:actor,'appointment.created',CAST(:details AS jsonb))",id=appt,actor=actor,details=json.dumps({'after':{'status':'booked','qualification':{'schema_version':3,'answers':{'construction_year':'2019','hydro_bill':'330 $ par mois','city':'Québec','comments':'Démonstration TXT sauvegardée'}}}}))
        result={'appointment':str(appt),'day':'2026-11-19'}
    elif payload['op']=='login_factor':
        encrypted=query(db,"SELECT mfa_secret FROM staging.identity_users WHERE id=:id AND email LIKE 'browser-admin-%@example.invalid'",id=payload['id']).scalar_one()
        result={'code':pyotp.TOTP(cipher.decrypt(encrypted.encode()).decode()).now()}
    elif payload['op']=='otp':
        result={'code':pyotp.TOTP(payload['secret']).now()}
    elif payload['op']=='expire':
        query(db,"UPDATE staging.identity_sessions SET expires_at=now()-interval '1 second' WHERE user_id=(SELECT id FROM staging.identity_users WHERE email=:email)",email=payload['email'])
        result={'status':'expired'}
    else:
        raise ValueError('Unknown browser fixture operation')
print(json.dumps(result))
'''.replace('PAYLOAD',repr(json.dumps(payload)))
r=subprocess.run([*compose,'exec','-T','api','python','-'],input=source,text=True,capture_output=True)
if r.returncode:
    raise SystemExit('Synthetic browser fixture operation failed')
print(r.stdout.strip())

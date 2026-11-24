"""Signed Voice HTTP -> PG -> sidecar HTTP/WS -> VM WS -> pre-bridge TwiML.

All contacts, keys, media and provider responses are synthetic. Only disposable
PostgreSQL and loopback sockets are used; never originate a telephone call.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import urlencode
from uuid import uuid4
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator
import uvicorn

from app.database import make_engine
from app.identity.security import new_token, digest
from app.identity.service import query
from app.main import app, lifespan
from app.telephony import service, completion, vmhunter as vm, vmhunter_screen as screen
from app.telephony.vmhunter_observer import Observer, Store, application
from app.telephony.twilio_voice import ManualVoiceProfile, client_identity, webhook_url
from app.reporting.service import report, Period

assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
assert os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:
    assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'

profile=ManualVoiceProfile('AC'+uuid4().hex,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
    'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100')
agents=[uuid4() for _ in range(3)];tokens=[new_token() for _ in agents]
contacts=[uuid4() for _ in agents];phones=['+14165550931','+14165550932','+14165550933']
browsers=[uuid4() for _ in agents];number=uuid4();stages={kind:uuid4() for kind in ('new','no_answer','other')}
pilot_value=dict(version=2,pilot_id=str(uuid4()),enabled=True,mode='screen',
    campaign_id=str(vm.PILOT_CAMPAIGN),agent_ids=[str(a) for a in agents[:2]],
    test_numbers=phones[:2],max_analyses=1000,audio_approved=True,screening_approved=True)
pilot=vm.Pilot.parse(pilot_value)
private=tempfile.TemporaryDirectory(prefix='vm-screen-proof-');policy_path=Path(private.name)/'pilot.json'
policy_path.write_text(json.dumps(pilot_value));policy_path.chmod(0o600)
os.environ['VMHUNTER_PILOT_FILE']=str(policy_path)

with engine.begin() as db:
    for agent,token in zip(agents,tokens):
        query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'Screen fixture','agent','unused')",
            id=agent,email=str(agent)+'@example.invalid')
        query(db,"INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at) VALUES (:token,:csrf,:actor,true,clock_timestamp()+interval '1 hour')",
            token=digest(token),csrf=digest(new_token()),actor=agent)
    query(db,"INSERT INTO staging.campaigns(id,name,timezone,created_by) VALUES (:id,'Screen synthetic','America/Toronto',:actor)",
        id=vm.PILOT_CAMPAIGN,actor=agents[0])
    for position,(kind,identifier) in enumerate(stages.items()):
        query(db,'INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position) VALUES (:id,:campaign,:kind,:kind,:color,:position)',
            id=identifier,campaign=vm.PILOT_CAMPAIGN,kind=kind,color='blue',position=position)
    query(db,"INSERT INTO staging.voice_numbers(id,account_sid,provider_sid,number,name,country,voice_enabled,verified_at) VALUES (:id,:account,:sid,:phone,'Synthetic','CA',true,clock_timestamp())",
        id=number,account=profile.account_sid,sid='PN'+uuid4().hex,phone=profile.caller_number)
    query(db,'INSERT INTO staging.voice_campaign_settings(campaign_id,enabled,default_number_id,updated_by) VALUES (:id,true,:number,:actor)',
        id=vm.PILOT_CAMPAIGN,number=number,actor=agents[0])
    query(db,"INSERT INTO staging.campaign_events(campaign_id,actor_id,action,details) VALUES (:campaign,:actor,'calling.settings_changed',CAST(:details AS jsonb))",
        campaign=vm.PILOT_CAMPAIGN,actor=agents[0],details=json.dumps({'after':{'policy':{'attempts_per_day':20,'retry_minutes':0,'ring_seconds':35}}}))
    for index,agent in enumerate(agents):
        query(db,'INSERT INTO staging.campaign_agents(campaign_id,user_id,assigned_by) VALUES (:campaign,:actor,:actor)',
            campaign=vm.PILOT_CAMPAIGN,actor=agent)
        query(db,'INSERT INTO staging.contacts(id,phone) VALUES (:id,:phone)',id=contacts[index],phone=phones[index])
        query(db,'INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id) VALUES (:campaign,:contact,:stage)',
            campaign=vm.PILOT_CAMPAIGN,contact=contacts[index],stage=stages['new'])
        query(db,"""INSERT INTO staging.voice_dialer_sessions(actor_id,session_hash,browser_id,campaign_id,mode,lease_until)
            VALUES (:actor,:session,:browser,:campaign,'running',clock_timestamp()+interval '90 seconds')""",
            actor=agent,session=digest(tokens[index]),browser=browsers[index],campaign=vm.PILOT_CAMPAIGN)


@asynccontextmanager
async def fixture_lifespan(application):
    async with lifespan(application):
        application.state.voice_profile=profile;application.state.voice_calling_enabled=True
        yield

app.router.lifespan_context=fixture_lifespan
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18021,log_level='critical',access_log=False))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
for _ in range(200):
    if server.started:break
    time.sleep(.025)
assert server.started


def new_call(index=0,automatic=True):
    identifier=uuid4()
    with engine.begin() as db:
        version=query(db,'SELECT version FROM staging.campaign_contacts WHERE campaign_id=:campaign AND contact_id=:contact',
            campaign=vm.PILOT_CAMPAIGN,contact=contacts[index]).scalar_one()
        query(db,"UPDATE staging.voice_dialer_sessions SET lease_until=clock_timestamp()+interval '90 seconds' WHERE actor_id=:id",id=agents[index])
        generation=query(db,'SELECT generation FROM staging.voice_dialer_sessions WHERE actor_id=:id',id=agents[index]).scalar_one()
        query(db,"""INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,
            application_sid,caller_number,destination,expires_at,campaign_id,contact_id,caller_number_id,
            membership_version,dialer_generation,dialer_browser_id)
            VALUES (:id,:actor,:session,:profile,:account,:application,:caller,:destination,
                clock_timestamp()+interval '2 minutes',:campaign,:contact,:number,:version,:generation,:browser)""",
            id=identifier,actor=agents[index],session=digest(tokens[index]),profile=service.profile_hash(profile),
            account=profile.account_sid,application=profile.twiml_app_sid,caller=profile.caller_number,
            destination=phones[index],campaign=vm.PILOT_CAMPAIGN,contact=contacts[index],number=number,
            version=version,generation=generation if automatic else None,browser=browsers[index] if automatic else None)
    return dict(id=identifier,index=index,parent='CA'+uuid4().hex,child='CA'+uuid4().hex)


def row(call):
    with engine.connect() as db:
        return dict(query(db,'SELECT * FROM staging.voice_intents WHERE id=:id',id=call['id']).mappings().one())


def events(call,kind):
    with engine.connect() as db:
        return list(query(db,'SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind=:kind ORDER BY id',id=call['id'],kind=kind).scalars())


async def signed(session,kind,call,fields,expected=200):
    intent=None if kind=='voice' else call['id']
    url=webhook_url(profile,kind,intent)
    values=FormData([('AccountSid',profile.account_sid),*fields.items()])
    signature=RequestValidator(profile.shared_key_secret).compute_signature(url,values)
    headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':signature,
        'X-Twilio-Webhooks-Signature-Settings':'key='+profile.shared_key_id+',algorithm=HMAC_SHA1'}
    async with session.post('http://127.0.0.1:18021'+url.removeprefix(profile.public_origin),
            data=urlencode(values.multi_items()),headers=headers) as response:
        raw=await response.read()
        assert response.status==expected,(kind,response.status,expected,raw[:250])
        return ET.fromstring(raw) if response.status==200 else None


async def voice(session,call,screened=True):
    xml=await signed(session,'voice',call,dict(CallSid=call['parent'],Intent=str(call['id']),
        From='client:'+client_identity(agents[call['index']],call['id'])))
    number=xml.find('Dial/Number');assert number is not None
    assert ('url' in number.attrib)==screened
    assert xml.find('Dial').attrib['record']=='record-from-answer-dual'


async def progress(session,call,status='in-progress',sequence='0'):
    return await signed(session,'status',call,dict(CallSid=call['child'],ParentCallSid=call['parent'],
        From=profile.caller_number,To=phones[call['index']],CallStatus=status,SequenceNumber=sequence,
        **({'CallDuration':'13'} if status=='completed' else {})))


async def finish_call(session,call,expected_mode='running',expected_generation=None):
    await progress(session,call,'completed','8')
    await signed(session,'finish',call,dict(CallSid=call['parent'],DialCallSid=call['child'],DialCallStatus='completed'))
    with engine.begin() as db:
        query(db,"UPDATE staging.voice_completion_jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE intent_id=:id",id=call['id'])
        assert completion.settle(db,call['id'])=='settled'
        state=query(db,'SELECT mode,generation FROM staging.voice_dialer_sessions WHERE actor_id=:id',id=agents[call['index']]).mappings().one()
        call_generation=query(db,'SELECT dialer_generation FROM staging.voice_intents WHERE id=:id',id=call['id']).scalar_one()
        expected_generation=expected_generation or call_generation or state['generation']
        assert state['mode']==expected_mode and state['generation']==expected_generation,'Screening changed agent controls'


async def wait_result(call):
    for _ in range(200):
        result=events(call,'vmhunter.result')
        if result:return result[0]
        await asyncio.sleep(.01)
    raise AssertionError('classification result missing')


async def main():
    provider_state={'answer':{'AMDSTATUS':'MACHINE','AMDCAUSE':'MACHINE_BEEP'},'gate':None}
    provider_configs=[];provider_audio=[]
    async def provider(request):
        ws=web.WebSocketResponse();await ws.prepare(request)
        try:
            config=await ws.receive_json();provider_configs.append(config)
            answer=dict(provider_state['answer']);gate=provider_state['gate']
            async for message in ws:
                if message.type==aiohttp.WSMsgType.BINARY:
                    provider_audio.append(message.data)
                    if gate:await gate.wait()
                    await ws.send_json(answer);break
        finally:await ws.close()
        return ws
    upstream_app=web.Application();upstream_app.router.add_get('/ws',provider)
    upstream=TestServer(upstream_app);await upstream.start_server()
    session=aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=10))

    class Streams:
        def __init__(self):self.started=0;self.stopped=0;self.stop_ok=True;self.pumps=[]
        async def start(self,payload,name,token):
            self.started+=1;sid='MZ'+uuid4().hex
            async def pump():
                async with session.ws_connect(sidecar.make_url('/api/telephony/vmhunter/media')) as ws:
                    await ws.send_json({'event':'connected','protocol':'Call','version':'1.0.0'})
                    await ws.send_json({'event':'start','start':{'streamSid':sid,'accountSid':profile.account_sid,
                        'callSid':payload['call_sid'],'tracks':['inbound'],'customParameters':{'ticket':token},
                        'mediaFormat':{'encoding':'audio/x-mulaw','sampleRate':8000,'channels':1}}})
                    await ws.send_json({'event':'media','streamSid':sid,'media':{'track':'inbound','chunk':'1',
                        'timestamp':'0','payload':base64.b64encode(b'\xff'*160).decode()}})
                    await ws.receive()
            self.pumps.append(asyncio.create_task(pump()))
            return sid
        async def stop(self,call,sid):self.stopped+=1;return self.stop_ok
        async def recover(self,call,name):return None

    streams=Streams()
    classifier=vm.Client('SYNTHETIC-KEY',session=session,endpoint=str(upstream.make_url('/ws')).replace('http:','ws:'))
    observer=Observer(profile,pilot,Store(engine,profile,pilot),streams,classifier)
    sidecar=TestServer(application(observer));await sidecar.start_server()
    old_rpc=screen.RPC_URL;screen.RPC_URL=str(sidecar.make_url('/private/observe'))
    try:
        # First call uses the actual signed Voice authorization and original Dial.
        first=new_call();await voice(session,first)
        await progress(session,first)
        await signed(session,'screen-start',first,
            dict(CallSid=first['child'],ParentCallSid='CA'+uuid4().hex),expected=403)
        await signed(session,'screen-start',first,
            dict(CallSid='CA'+uuid4().hex,ParentCallSid=first['parent']),expected=403)
        assert not events(first,'vmhunter.claim')
        assert row(first)['state']!='answered','PSTN answer exposed as agent conversation before screening'
        fields=dict(CallSid=first['child'],ParentCallSid=first['parent'])
        xml=await signed(session,'screen-start',first,fields)
        assert xml.find('Gather/Say').text==screen.GREETING
        await wait_result(first)
        xml=await signed(session,'screen-result',first,fields)
        assert xml.find('Hangup') is not None
        assert len(events(first,'disposition.voicemail'))==1
        # A late child status must not expose a rejected voicemail as connected.
        await progress(session,first,sequence='1')
        assert row(first)['state']!='answered','Late in-progress overrode the rejected pre-bridge decision'
        assert (await signed(session,'screen-result',first,fields)).find('Hangup') is not None
        assert len(events(first,'disposition.voicemail'))==1
        await finish_call(session,first)
        with engine.connect() as db:
            assert query(db,'SELECT stage_id FROM staging.campaign_contacts WHERE campaign_id=:campaign AND contact_id=:contact',
                campaign=vm.PILOT_CAMPAIGN,contact=contacts[0]).scalar_one()==stages['no_answer']
            day=row(first)['consumed_at'].astimezone(ZoneInfo('America/Toronto')).date()
            totals=report(db,Period(day,day,'America/Toronto'),agents[0])['totals']
            assert totals['voicemail']==1 and totals['answered']==0 and totals['talk_seconds']==0

        results=[('HUMAN','HUMAN'),('MACHINE','INITIALSILENCE'),('MACHINE','MAXWORD'),
            ('MACHINE','MACHINE_STATIC'),('MACHINE','CALLGUARD_PHRASE:synthetic screen'),
            ('CALLGUARD','CALLGUARD_PHRASE:synthetic screen'),('FAILED','LIMIT_REACHED'),
            ('FAILED','AUTH_FAILED'),('MACHINE','future_unknown')]
        for status,cause in results:
            provider_state['answer']={'AMDSTATUS':status,'AMDCAUSE':cause}
            call=new_call();await voice(session,call);await progress(session,call)
            fields=dict(CallSid=call['child'],ParentCallSid=call['parent'])
            await signed(session,'screen-start',call,fields);await wait_result(call)
            assert len(list(await signed(session,'screen-result',call,fields)))==0,(status,cause)
            assert row(call)['state']=='answered'
            assert not events(call,'disposition.voicemail')
            await finish_call(session,call)
            if status=='FAILED':
                bypass=new_call(1);await voice(session,bypass);await progress(session,bypass)
                before=streams.started
                fields=dict(CallSid=bypass['child'],ParentCallSid=bypass['parent'])
                assert len(list(await signed(session,'screen-start',bypass,fields)))==0
                assert streams.started==before,'Provider outage started another paid stream during backoff'
                await finish_call(session,bypass)
            # Independent matrix cases reset only this test clock's cooldown;
            # production expiry is covered by a dedicated injected-clock test.
            observer.backoff_until=0

        # A pressed key is affirmative human input, even with a machine result.
        provider_state['answer']={'AMDSTATUS':'MACHINE','AMDCAUSE':'MACHINE_BEEP'}
        keyed=new_call();await voice(session,keyed);await progress(session,keyed)
        fields=dict(CallSid=keyed['child'],ParentCallSid=keyed['parent'])
        await signed(session,'screen-start',keyed,fields);await wait_result(keyed)
        assert len(list(await signed(session,'screen-result',keyed,fields | {'Digits':'#'})))==0
        assert not events(keyed,'disposition.voicemail');await finish_call(session,keyed)

        # A late machine result cannot reverse the already released bridge.
        gate=asyncio.Event();provider_state['gate']=gate
        late=new_call();await voice(session,late);await progress(session,late)
        fields=dict(CallSid=late['child'],ParentCallSid=late['parent'])
        await signed(session,'screen-start',late,fields)
        assert len(list(await signed(session,'screen-result',late,fields)))==0
        gate.set();await wait_result(late);provider_state['gate']=None
        assert len(list(await signed(session,'screen-result',late,fields)))==0
        assert not events(late,'disposition.voicemail');await finish_call(session,late)

        # A later human pipeline edit wins even when another greeting was
        # confidently classified as a machine (without a beep).
        provider_state['answer']={'AMDSTATUS':'MACHINE','AMDCAUSE':'MACHINE'}
        changed=new_call();await voice(session,changed);await progress(session,changed)
        fields=dict(CallSid=changed['child'],ParentCallSid=changed['parent'])
        await signed(session,'screen-start',changed,fields);await wait_result(changed)
        assert (await signed(session,'screen-result',changed,fields)).find('Hangup') is not None
        with engine.begin() as db:
            query(db,'UPDATE staging.campaign_contacts SET stage_id=:stage,version=version+1 WHERE campaign_id=:campaign AND contact_id=:contact',
                stage=stages['other'],campaign=vm.PILOT_CAMPAIGN,contact=contacts[0])
        await finish_call(session,changed)
        with engine.connect() as db:
            assert query(db,'SELECT stage_id FROM staging.campaign_contacts WHERE campaign_id=:campaign AND contact_id=:contact',
                campaign=vm.PILOT_CAMPAIGN,contact=contacts[0]).scalar_one()==stages['other']

        # Actual deadline expiration: late action delivery must release the
        # customer even when a previously confident machine result is available.
        expired=new_call();await voice(session,expired);await progress(session,expired)
        fields=dict(CallSid=expired['child'],ParentCallSid=expired['parent'])
        await signed(session,'screen-start',expired,fields);await wait_result(expired)
        # A transient DB failure can return the ordinary bridge before a
        # screen-start event exists. Its later answer status must still recover.
        from unittest.mock import patch
        from sqlalchemy.exc import OperationalError
        no_start=new_call(1);await voice(session,no_start);await progress(session,no_start)
        with patch.object(screen,'begin',side_effect=OperationalError('synthetic outage',{},None)):
            assert len(list(await signed(session,'screen-start',no_start,
                dict(CallSid=no_start['child'],ParentCallSid=no_start['parent']))))==0
        assert not events(no_start,'vmhunter.screen.started')
        await asyncio.sleep(8.1)
        await progress(session,no_start,sequence='1')
        assert row(no_start)['state']=='answered','Missing screen-start blocked ordinary status recovery indefinitely'
        before=streams.started
        assert len(list(await signed(session,'screen-start',no_start,
            dict(CallSid=no_start['child'],ParentCallSid=no_start['parent']))))==0
        assert streams.started==before,'Delayed screen-start restarted analysis after ordinary recovery'
        assert not events(no_start,'disposition.voicemail');await finish_call(session,no_start)
        await progress(session,expired,sequence='1')
        assert row(expired)['state']=='answered','Expired screening blocked ordinary status recovery'
        assert len(list(await signed(session,'screen-result',expired,fields)))==0
        assert not events(expired,'disposition.voicemail');await finish_call(session,expired)

        # Ringing time is not screening time: an older reservation must still
        # screen normally once the called party actually answers.
        long_ring=new_call(1);await voice(session,long_ring)
        await asyncio.sleep(8.1)
        await progress(session,long_ring)
        fields=dict(CallSid=long_ring['child'],ParentCallSid=long_ring['parent'])
        assert (await signed(session,'screen-start',long_ring,fields)).find('Gather') is not None
        await wait_result(long_ring)
        assert (await signed(session,'screen-result',long_ring,fields)).find('Hangup') is not None
        await finish_call(session,long_ring)

        # Agent pause and stop affect the next call, and must never be undone by
        # a current call's successful filtering/completion.
        for mode in ('paused','stopped'):
            controlled=new_call();await voice(session,controlled);await progress(session,controlled)
            with engine.begin() as db:
                generation=query(db,"UPDATE staging.voice_dialer_sessions SET mode=:mode,generation=generation+1 WHERE actor_id=:id RETURNING generation",
                    mode=mode,id=agents[0]).scalar_one()
            fields=dict(CallSid=controlled['child'],ParentCallSid=controlled['parent'])
            await signed(session,'screen-start',controlled,fields);await wait_result(controlled)
            assert (await signed(session,'screen-result',controlled,fields)).find('Hangup') is not None
            await finish_call(session,controlled,expected_mode=mode,expected_generation=generation)
            with engine.begin() as db:
                query(db,"UPDATE staging.voice_dialer_sessions SET mode='running',generation=generation+1 WHERE actor_id=:id",id=agents[0])

        # Two real local HTTP/WS jobs can execute concurrently with separate legs.
        provider_state['answer']={'AMDSTATUS':'HUMAN','AMDCAUSE':'HUMAN'}
        concurrent=[new_call(0),new_call(1)]
        await asyncio.gather(*(voice(session,c) for c in concurrent))
        await asyncio.gather(*(progress(session,c) for c in concurrent))
        before=streams.started
        async def run(c):
            fields=dict(CallSid=c['child'],ParentCallSid=c['parent'])
            await signed(session,'screen-start',c,fields);await wait_result(c)
            assert len(list(await signed(session,'screen-result',c,fields)))==0
            await finish_call(session,c)
        await asyncio.gather(*(run(c) for c in concurrent))
        assert streams.started==before+2

        # Unselected agents and manual calls keep their exact ordinary call path.
        before=streams.started
        for c in (new_call(2),new_call(0,automatic=False)):
            await voice(session,c,screened=False)
            assert row(c)['child_call_sid'] is None
            unexpected=await signed(session,'screen-start',c,
                dict(CallSid='CA'+uuid4().hex,ParentCallSid=c['parent']))
            assert len(list(unexpected))==0 and row(c)['child_call_sid'] is None
            await progress(session,c)
            assert row(c)['state']=='answered';await finish_call(session,c)
        assert streams.started==before

        # Missing sidecar is a successful immediate bridge response, not HTTP 500.
        unavailable=new_call();await voice(session,unavailable);await progress(session,unavailable)
        saved=screen.RPC_URL;screen.RPC_URL='http://127.0.0.1:1/private/observe'
        fields=dict(CallSid=unavailable['child'],ParentCallSid=unavailable['parent'])
        assert len(list(await signed(session,'screen-start',unavailable,fields)))==0
        screen.RPC_URL=saved;assert not events(unavailable,'disposition.voicemail')
        await finish_call(session,unavailable)

        # A cleanup failure cannot reject a caller and disables later analyses.
        streams.stop_ok=False;provider_state['answer']={'AMDSTATUS':'MACHINE','AMDCAUSE':'MACHINE_BEEP'}
        cleanup=new_call();await voice(session,cleanup);await progress(session,cleanup)
        fields=dict(CallSid=cleanup['child'],ParentCallSid=cleanup['parent'])
        await signed(session,'screen-start',cleanup,fields);await wait_result(cleanup)
        assert len(list(await signed(session,'screen-result',cleanup,fields)))==0
        assert observer.degraded and not events(cleanup,'disposition.voicemail')
        await finish_call(session,cleanup)
        bypass=new_call(1);await voice(session,bypass);await progress(session,bypass)
        before=streams.started
        assert len(list(await signed(session,'screen-start',bypass,dict(CallSid=bypass['child'],ParentCallSid=bypass['parent']))))==0
        assert streams.started==before;await finish_call(session,bypass)

        assert provider_audio and all(frame==b'\0'*320 for frame in provider_audio)
        assert all(config['config']['sample_rate']==8000 for config in provider_configs)
        print(json.dumps({'signed_voice_to_prebridge_pipeline':True,'safe_decisions':len(results)+10,
            'real_local_two_agent_concurrency':True,'voicemail_excluded_from_talk':True,
            'voicemail_pipeline_no_answer':True,'dialers_remain_running':True,
            'manual_and_unselected_unchanged':True,'human_pipeline_edit_preserved':True,'actual_deadline_recovery':True,
            'explicit_pause_and_stop_preserved':True,
            'missing_start_database_outage_recovers':True,
            'late_start_cannot_reverse_recovery':True,'ringing_does_not_expire_screening':True,
            'provider_analyses':len(provider_configs),'real_calls':0}))
    finally:
        screen.RPC_URL=old_rpc
        await sidecar.close()
        await asyncio.gather(*streams.pumps,return_exceptions=True)
        await upstream.close();await session.close()


try:
    asyncio.run(main())
finally:
    server.should_exit=True;thread.join(timeout=8)
    os.environ.pop('VMHUNTER_PILOT_FILE',None);private.cleanup();engine.dispose()

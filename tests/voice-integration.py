"""Real HTTP + PostgreSQL with synthetic Twilio signatures, no provider calls."""
import asyncio
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from http.client import HTTPConnection
import os
import threading
import time
from urllib.parse import urlencode
import urllib.error
import urllib.request
from uuid import uuid4
from xml.etree import ElementTree

from sqlalchemy.exc import DBAPIError
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator
import uvicorn

from app.database import make_engine
from app.identity.security import COOKIE, CSRF_COOKIE, digest, new_token
from app.identity.service import query
from app.main import app, lifespan
from app.telephony.twilio_voice import ControlledVoiceProfile, client_identity, webhook_url

assert os.environ['DB_HOST'] == 'db' and os.environ.get('DB_DEPLOYMENT', 'local') == 'local'
assert os.environ['COMMUNICATIONS_MODE'] == 'disabled'
engine = make_engine()
with engine.connect() as db:
    assert query(db, "SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one() == 'synthetic_only'

profile = ControlledVoiceProfile('AC'+'a'*32, 'SK'+'b'*32, 'c'*32, 'AP'+'d'*32,
    'webhooks_sharedkey_'+'e'*26, 'f'*32, 'https://voice.example.invalid', '+14165550100', '+14165550101')
base = 'http://127.0.0.1:18001'
origin = os.environ['APP_ORIGIN']


@asynccontextmanager
async def fixture_lifespan(application):
    # Never enable a real profile: only this disposable test process injects a
    # synthetic provider after the normal disabled-mode startup has completed.
    async with lifespan(application):
        application.state.voice_profile = profile
        application.state.voice_calling_enabled = True
        yield


app.router.lifespan_context = fixture_lifespan
server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=18001, log_level='critical', access_log=False))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
for _ in range(200):
    if server.started:
        break
    time.sleep(0.025)
assert server.started


def http(method, path, body=None, headers=None):
    request = urllib.request.Request(base + path, data=body, headers=headers or {}, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.read(), response.headers


class Browser:
    def __init__(self, role='admin', verified=True):
        self.id = uuid4()
        self.token, self.csrf = new_token(), new_token()
        with engine.begin() as db:
            query(db, '''INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret)
                VALUES (:id,:email,'Voice fixture',:role,'unused',:mfa)''',
                id=self.id, email=str(self.id)+'@example.invalid', role=role,
                mfa=app.state.identity_cipher.encrypt(b'JBSWY3DPEHPK3PXP').decode() if role=='admin' else None)
            query(db, '''INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at)
                VALUES (:token,:csrf,:user,:verified,now()+interval '1 hour')''',
                token=digest(self.token), csrf=digest(self.csrf), user=self.id, verified=verified)

    def request(self, method, path, body=None, expected=200, **changes):
        headers = {'Cookie': COOKIE+'='+self.token+'; '+CSRF_COOKIE+'='+self.csrf,
                   'X-CSRF-Token': self.csrf, 'Origin': origin, 'Content-Type': 'application/json'}
        headers.update(changes)
        status, raw, response_headers = http(method, path, json.dumps(body).encode() if body is not None else None, headers)
        assert status == expected, (method, path, status, expected, raw[:300])
        assert response_headers['Cache-Control'] == 'no-store'
        return json.loads(raw)

    def reserve(self, identifier=None, expected=201):
        identifier = identifier or uuid4()
        result = self.request('POST', '/api/telephony/test/intents', {'id': str(identifier)}, expected)
        return identifier, result


def signed(kind, identifier=None, fields=None, expected=200, **headers):
    fields = list((fields or {}).items())
    parameters = FormData([('AccountSid', profile.account_sid), *fields])
    url = webhook_url(profile, kind, identifier)
    signature = RequestValidator(profile.shared_key_secret).compute_signature(url, parameters)
    settings = {'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': signature,
                'X-Twilio-Webhooks-Signature-Settings': 'key='+profile.shared_key_id+',algorithm=HMAC_SHA1',
                'X-Forwarded-Host': 'untrusted.example.invalid', 'X-Forwarded-Proto': 'http'}
    settings.update(headers)
    path = url.removeprefix(profile.public_origin)
    status, raw, _ = http('POST', path, urlencode(parameters.multi_items()).encode(), settings)
    assert status == expected, (kind, status, expected, raw[:300])
    return ElementTree.fromstring(raw) if status == 200 else raw


def voice(browser, identifier, parent=None, expected=200):
    parent = parent or 'CA'+uuid4().hex
    return parent, signed('voice', fields={'CallSid': parent, 'Intent': str(identifier),
                                        'From': 'client:'+client_identity(browser.id, identifier)}, expected=expected)


def row(identifier):
    with engine.connect() as db:
        return dict(query(db, 'SELECT * FROM staging.voice_intents WHERE id=:id', id=identifier).mappings().one())


def expire(identifier):
    with engine.begin() as db:
        query(db, '''UPDATE staging.voice_intents SET created_at=clock_timestamp()-interval '3 minutes',
            expires_at=clock_timestamp()-interval '1 minute' WHERE id=:id''', id=identifier)


try:
    browser = Browser()
    # Off mode and unauthenticated/CSRF/origin/role failures cannot reserve.
    app.state.voice_profile = None
    browser.reserve(expected=503)
    app.state.voice_profile = profile
    app.state.voice_calling_enabled = False
    browser.reserve(expected=503)
    off_session=browser.request('GET','/api/telephony/test/session')
    assert off_session['enabled'] is False and off_session['active'] is None and 'token' not in off_session
    app.state.voice_calling_enabled = True
    assert http('POST','/api/telephony/test/intents',json.dumps({'id':str(uuid4())}).encode(),{'Origin':origin,'Content-Type':'application/json'})[0] == 401
    agent = Browser('agent')
    agent.reserve(expected=403)
    agent.request('GET','/api/telephony/test/session',expected=403)
    assert http('GET','/api/telephony/test/session')[0]==401
    unenrolled = Browser(verified=False)
    unenrolled.reserve(expected=403)
    browser.request('POST','/api/telephony/test/intents',{'id':str(uuid4())},403,Origin='https://untrusted.example.invalid')
    browser.request('POST','/api/telephony/test/intents',{'id':str(uuid4())},403,**{'X-CSRF-Token':'wrong'})
    browser.request('POST','/api/telephony/test/intents',{'id':str(uuid4()),'To':'+14165550109'},422)
    hook='/api/telephony/twilio/voice'
    assert http('GET',hook)[0]==405
    assert http('POST',hook,b'not-signed',{'Content-Type':'application/x-www-form-urlencoded'})[0]==403
    assert http('POST',hook+'?unexpected=1',b'k=v',{'Content-Type':'application/x-www-form-urlencoded'})[0]==400
    assert http('POST',hook,b'x'*16385,{'Content-Type':'application/x-www-form-urlencoded'})[0]==413
    assert http('POST',hook,iter([b'x'*8192,b'x'*8193]),{'Content-Type':'application/x-www-form-urlencoded'})[0]==413
    duplicate=HTTPConnection('127.0.0.1',18001,timeout=5)
    duplicate.putrequest('POST',hook)
    duplicate.putheader('Content-Type','application/x-www-form-urlencoded')
    duplicate.putheader('Content-Length','0')
    duplicate.putheader('X-Twilio-Signature','A'*27+'=')
    duplicate.putheader('X-Twilio-Signature','A'*27+'=')
    duplicate.endheaders()
    response=duplicate.getresponse();assert response.status==400;response.read();duplicate.close()
    identifier, first = browser.reserve()
    current=browser.request('GET','/api/telephony/test/session')
    assert current['enabled'] is True and current['active']['id']==str(identifier) and current['active']['owned_session'] is True
    assert current['destination']==profile.approved_destination and current['max_duration_seconds']==180
    assert not any(k in json.dumps(current) for k in ('token','profile_hash','session_hash','api_key'))
    assert first['intent']['state'] == 'reserved' and first['token']
    assert browser.reserve(identifier)[1]['intent']['id'] == str(identifier)
    app.state.voice_calling_enabled = False
    assert voice(browser,identifier)[1].find('Dial') is None
    assert row(identifier)['state']=='reserved'
    app.state.voice_calling_enabled = True
    signed('probe',fields={'Test':'true'},expected=204)
    signed('probe',fields={'Test':'true'},expected=403,**{'X-Twilio-Signature':'A'*27+'='})
    browser.reserve(expected=409)
    other = Browser()
    assert other.request('GET','/api/telephony/test/session')['active'] is None
    other.reserve(expected=409)
    assert signed('voice',fields={'CallSid':'CA'+uuid4().hex,'Intent':str(identifier),
        'From':'client:'+client_identity(browser.id,identifier)}, expected=403, **{'X-Twilio-Signature':'A'*27+'='})
    assert row(identifier)['state'] == 'reserved'
    # Concurrent valid requests can receive at most one Dial, even different CAs.
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: voice(browser,identifier), range(2)))
    assert sum(xml.find('Dial') is not None for _,xml in responses) == 1
    parent = row(identifier)['parent_call_sid']
    dial = next(xml.find('Dial') for _,xml in responses if xml.find('Dial') is not None)
    assert dial.find('Number').text == profile.approved_destination
    assert dial.attrib['timeLimit'] == '180' and dial.attrib['record'] == 'record-from-answer-dual'
    assert voice(browser,identifier,parent)[1].find('Dial') is None
    browser.request('POST','/api/telephony/test/intents/'+str(identifier)+'/cancel',expected=409)
    recording = 'RE'+uuid4().hex
    record_fields = dict(CallSid=parent,RecordingSid=recording,RecordingStatus='completed',RecordingDuration='12',
                         RecordingChannels='2',RecordingSource='DialVerb',RecordingUrl='http://169.254.169.254/never-fetch-this')
    # Recording completion may precede ALL child/finish notifications. Its
    # parent was already durably bound before the only Dial response.
    signed('recording',identifier,record_fields)
    child = 'CA'+uuid4().hex
    status_fields = dict(CallSid=child,ParentCallSid=parent,To=profile.approved_destination,From=profile.caller_number,
                         CallStatus='ringing',SequenceNumber='1')
    signed('status',identifier,{**status_fields,'ParentCallSid':'CA'+uuid4().hex},403)
    signed('status',identifier,status_fields)
    assert row(identifier)['state'] == 'ringing'
    signed('status',identifier,{**status_fields,'CallStatus':'busy','SequenceNumber':'3'})
    signed('status',identifier,{**status_fields,'CallStatus':'in-progress','SequenceNumber':'2'})
    signed('status',identifier,{**status_fields,'CallStatus':'busy','SequenceNumber':'3'})
    assert row(identifier)['state'] == 'finished' and row(identifier)['outcome'] == 'busy'
    signed('parent-status',fields={'CallSid':parent,'CallStatus':'completed'})
    signed('finish',identifier,{'CallSid':parent,'DialCallSid':child,'DialCallStatus':'busy'})
    assert row(identifier)['outcome'] == 'busy'
    signed('recording',identifier,{**record_fields,'CallSid':'CA'+uuid4().hex},403)
    signed('recording',identifier,{**record_fields,'RecordingSource':'StartCallRecordingAPI'},403)
    signed('recording',identifier,{**record_fields,'RecordingChannels':'1'},400)
    signed('recording',identifier,record_fields)
    signed('recording',identifier,record_fields)
    history = browser.request('GET','/api/telephony/test/intents/'+str(identifier))
    assert len(history['recordings']) == 1 and history['recordings'][0]['state'] == 'pending_archive'
    assert sum(event['kind']=='recording' for event in history['events']) == 1
    assert sum(event['kind']=='status' for event in history['events']) == 3
    assert '169.254' not in json.dumps(history) and 'RecordingUrl' not in json.dumps(history)
    # Revoked sessions, changed roles, stale reservations and profile changes
    # cannot redeem a previously minted token. Call history survives revocation.
    for operation in ['revoke','deactivate','role','expire']:
        user = Browser()
        pending,_ = user.reserve()
        with engine.begin() as db:
            if operation == 'revoke':
                query(db,'DELETE FROM staging.identity_sessions WHERE user_id=:id',id=user.id)
            elif operation == 'deactivate':
                query(db,'UPDATE staging.identity_users SET is_active=false WHERE id=:id',id=user.id)
            elif operation == 'role':
                query(db,"UPDATE staging.identity_users SET role='agent' WHERE id=:id",id=user.id)
        if operation == 'expire':
            expire(pending)
        assert voice(user,pending)[1].find('Dial') is None
        assert row(pending)['state'] in {'cancelled','expired'}
    # Browser retries and two admins cannot obtain competing target reservations.
    competitors = [Browser(),Browser()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        def compete(user):
            iid=uuid4()
            status,raw,_=http('POST','/api/telephony/test/intents',json.dumps({'id':str(iid)}).encode(),
                {'Cookie':COOKIE+'='+user.token+'; '+CSRF_COOKIE+'='+user.csrf,'X-CSRF-Token':user.csrf,
                 'Origin':origin,'Content-Type':'application/json'})
            return status,iid,user
        competed=list(pool.map(compete,competitors))
    assert sorted(status for status,_,_ in competed) == [201,409]
    _,pending,user=next(item for item in competed if item[0]==201)
    user.request('POST','/api/telephony/test/intents/'+str(pending)+'/cancel')
    assert voice(user,pending)[1].find('Dial') is None
    # No time-based release of an authorized call with missing provider results.
    uncertain_user=Browser()
    uncertain,_=uncertain_user.reserve()
    uncertain_parent,_=voice(uncertain_user,uncertain)
    expire(uncertain)
    uncertain_user.reserve(expected=409)
    assert row(uncertain)['state']=='authorized'
    signed('parent-status',fields={'CallSid':uncertain_parent,'CallStatus':'completed'})
    # A valid signature from the same account cannot reassign a recording to a
    # different intent/call, and provider URLs are never stored or downloaded.
    second_user=Browser()
    second,_=second_user.reserve()
    second_parent,_=voice(second_user,second)
    signed('recording',second,{**record_fields,'CallSid':second_parent},403)
    signed('parent-status',fields={'CallSid':second_parent,'CallStatus':'completed'})
    # Polling recovery is tested against the same real PG and HTTP callbacks.
    # No network read may retain a DB connection/transaction across the wait.
    from app.telephony.reconciliation import (Observation, ProviderReadError, reconcile_once,
                                              candidates, apply_observation)

    def old_consumed(identifier):
        with engine.begin() as db:
            query(db, '''UPDATE staging.voice_intents SET created_at=clock_timestamp()-interval '90 seconds',
                expires_at=clock_timestamp()+interval '30 seconds',consumed_at=clock_timestamp()-interval '30 seconds'
                WHERE id=:id''',id=identifier)

    recovery_user=Browser()
    recover_id,_=recovery_user.reserve()
    recover_parent,_=voice(recovery_user,recover_id)

    class Provider:
        def __init__(self,parent='completed',child=None,status=None,fail=False,hook=None):
            self.parent,self.child,self.status,self.fail,self.hook=parent,child,status,fail,hook
            self.reads=0
        def read(self,pending):
            self.reads+=1
            assert engine.pool.checkedout()==0,'Network read retained a DB connection'
            if self.hook:self.hook()
            if self.fail:raise ProviderReadError('provider_unavailable')
            return Observation(pending,self.parent,self.child,self.status)

    provider=Provider()
    assert reconcile_once(engine,profile,provider)['checked']==0 and provider.reads==0
    old_consumed(recover_id)
    failed=reconcile_once(engine,profile,Provider(fail=True))
    assert failed['failed']==1 and row(recover_id)['state']=='authorized'
    still_active=reconcile_once(engine,profile,Provider(parent='in-progress'))
    assert still_active['pending']==1 and row(recover_id)['state']=='authorized'
    # A consumed call can finish after session revocation. Recovery does not
    # require a human session and cannot grant another token or call.
    with engine.begin() as db:
        query(db,'DELETE FROM staging.identity_sessions WHERE user_id=:id',id=recovery_user.id)
    recovered=reconcile_once(engine,profile,provider)
    assert recovered['recovered']==1 and row(recover_id)['state']=='finished'
    assert reconcile_once(engine,profile,provider)['checked']==0

    race_user=Browser()
    race_id,_=race_user.reserve();race_parent,_=voice(race_user,race_id);old_consumed(race_id)
    race_child='CA'+uuid4().hex
    # A child bound AFTER the snapshot must block an observation which did not
    # read that child, even when its parent was reported as completed.
    def late_child():
        signed('status',race_id,dict(CallSid=race_child,ParentCallSid=race_parent,From=profile.caller_number,
            To=profile.approved_destination,CallStatus='in-progress',SequenceNumber='0'))
    stale=reconcile_once(engine,profile,Provider(hook=late_child))
    assert stale['stale']==1 and row(race_id)['state']=='answered'
    parent_not_finished=reconcile_once(engine,profile,Provider(parent='in-progress',child=race_child,status='completed'))
    assert parent_not_finished['pending']==1 and row(race_id)['state']=='answered'
    assert reconcile_once(engine,profile,Provider(child=race_child,status='busy'))['recovered']==1
    assert row(race_id)['outcome']=='busy'

    callback_user=Browser()
    callback_id,_=callback_user.reserve();callback_parent,_=voice(callback_user,callback_id);old_consumed(callback_id)
    def late_final():signed('parent-status',fields={'CallSid':callback_parent,'CallStatus':'completed'})
    assert reconcile_once(engine,profile,Provider(hook=late_final))['stale']==1
    assert row(callback_id)['state']=='finished'

    duplicate_user=Browser()
    duplicate_id,_=duplicate_user.reserve();_,_=voice(duplicate_user,duplicate_id);old_consumed(duplicate_id)
    snapshot=next(p for p in candidates(engine,profile) if p.id==duplicate_id)
    observation=Observation(snapshot,'completed',None,None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:apply_observation(engine,profile,observation),range(2)))
    assert sorted(results)==['recovered','resolved_elsewhere']
    with engine.connect() as db:
        assert query(db,"SELECT count(*) FROM staging.voice_events WHERE intent_id=:id AND kind='reconciliation.observed'",id=duplicate_id).scalar_one()==1
    # Durable archive claim/retry plus real private object-store and authenticated
    # HTTP Range playback. No provider network requests or real telephone calls.
    import io,wave
    from app.telephony import recording_archive as archive,archive_storage
    from app.telephony.service import profile_hash
    from app.contacts.storage import client as storage_client
    transport,bucket=storage_client()
    try:transport.head_bucket(Bucket=bucket)
    except Exception:transport.create_bucket(Bucket=bucket)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=list(pool.map(lambda _:archive.claim(engine,profile),range(2)))
    assert sum(job is not None for job in jobs)==1
    job=next(job for job in jobs if job is not None)
    assert job.recording_sid==recording and engine.pool.checkedout()==0
    assert archive.fail(engine,job,'raw credentials must never be persisted')
    assert archive.claim(engine,profile) is None  # retry delay is durable
    with engine.begin() as db:
        saved=query(db,'SELECT * FROM staging.voice_archive_jobs WHERE recording_sid=:sid',sid=recording).mappings().one()
        assert saved['last_error_code']=='provider_unavailable' and saved['attempts']==1
        query(db,"UPDATE staging.voice_archive_jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE recording_sid=:sid",sid=recording)
    retry=archive.claim(engine,profile)
    assert retry.attempts==2 and retry.lease_token!=job.lease_token
    assert archive.fail(engine,job,'provider_unavailable') is False  # stale owner
    # Simulate a worker dying after claiming, then recover its expired lease.
    with engine.begin() as db:
        query(db,"UPDATE staging.voice_archive_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE recording_sid=:sid",sid=recording)
    recovered_job=archive.claim(engine,profile)
    assert recovered_job.lease_token!=retry.lease_token
    data=io.BytesIO()
    with wave.open(data,'wb') as wav:
        wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(8000)
        wav.writeframes(b'\x00\x00'*2*8000*recovered_job.duration)
    content=data.getvalue()
    assert engine.pool.checkedout()==0
    key,checksum=archive_storage.put(recovered_job.intent_id,recovered_job.recording_sid,content)
    assert archive.finish(engine,profile,retry,content,key,checksum)=='stale'
    assert archive.finish(engine,profile,recovered_job,content,key,checksum)=='archived'
    assert archive.finish(engine,profile,recovered_job,content,key,checksum)=='resolved_elsewhere'
    assert archive.claim(engine,profile) is None
    assert transport.get_object_acl(Bucket=bucket,Key=key)['Grants'][0]['Permission']=='FULL_CONTROL'
    # Existing admin session remains authorized; a different ordinary agent gets
    # a non-enumerating 404. No provider/storage URL is sent to the browser.
    playback='/api/telephony/recordings/'+recording+'/audio'
    admin_view=Browser()
    status,audio_bytes,headers=http('GET',playback,headers={'Cookie':COOKIE+'='+admin_view.token})
    assert status==200 and audio_bytes==content and headers['Cache-Control']=='no-store'
    assert headers['Content-Type'].startswith('audio/wav') and not headers.get('Location')
    status,chunk,headers=http('GET',playback,headers={'Cookie':COOKIE+'='+admin_view.token,'Range':'bytes=10-29'})
    assert status==206 and chunk==content[10:30] and headers['Content-Range']==f'bytes 10-29/{len(content)}'
    other_agent=Browser(role='agent')
    assert http('GET',playback,headers={'Cookie':COOKIE+'='+other_agent.token})[0]==404
    assert http('GET',playback)[0]==401
    # Storage corruption cannot be played, even under an authenticated session.
    transport.put_object(Bucket=bucket,Key=key,Body=b'changed',ACL='private')
    assert http('GET',playback,headers={'Cookie':COOKIE+'='+admin_view.token})[0]==503
    transport.put_object(Bucket=bucket,Key=key,Body=content,ACL='private',ContentType='audio/wav')
    # The worker's complete path releases DB connections before both external
    # operations and retries a failed upload without losing the recording.
    second_recording='RE'+uuid4().hex
    signed('recording',identifier,{**record_fields,'RecordingSid':second_recording})
    class MediaReader:
        def read(self,job):
            assert engine.pool.checkedout()==0
            return content
    def broken_upload(*args):
        assert engine.pool.checkedout()==0
        raise RuntimeError('synthetic storage outage')
    assert archive.archive_once(engine,profile,MediaReader(),broken_upload)=='retry_scheduled'
    with engine.begin() as db:
        query(db,"UPDATE staging.voice_archive_jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE recording_sid=:sid",sid=second_recording)
    def upload(*args):
        assert engine.pool.checkedout()==0
        return archive_storage.put(*args)
    assert archive.archive_once(engine,profile,MediaReader(),upload)=='archived'
    # Agent ownership and stable cursor pagination are independent of whether
    # an agent is allowed to originate the controlled admin-only test.
    with engine.begin() as db:
        query(db,"UPDATE staging.identity_users SET role='agent' WHERE id=:id",id=browser.id)
        for _ in range(21):
            query(db,'''INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,
                caller_number,destination,state,parent_call_sid,expires_at,consumed_at,finished_at)
                VALUES (:id,:actor,:session,:profile,:account,:application,:caller,:destination,'finished',:call,
                    clock_timestamp()+interval '2 minutes',clock_timestamp(),clock_timestamp())''',
                id=uuid4(),actor=other_agent.id,session=digest(other_agent.token),profile=profile_hash(profile),
                account=profile.account_sid,application=profile.twiml_app_sid,caller=profile.caller_number,
                destination=profile.approved_destination,call='CA'+uuid4().hex)
    assert http('GET',playback,headers={'Cookie':COOKIE+'='+browser.token})[0]==200
    page1=other_agent.request('GET','/api/telephony/calls')
    assert len(page1['items'])==20 and page1['next_cursor']
    cursor=page1['next_cursor']
    page2=other_agent.request('GET','/api/telephony/calls?'+urlencode({'before_id':cursor['id'],'before_created_at':cursor['created_at']}))
    assert len(page2['items'])==1 and page2['next_cursor'] is None
    assert not ({c['id'] for c in page1['items']} & {c['id'] for c in page2['items']})
    other_agent.request('GET','/api/telephony/calls?before_id='+cursor['id'],expected=400)
    serialized=json.dumps(page1)
    assert all(name not in serialized for name in ['object_key','checksum','session_hash','profile_hash','api_key_secret'])
    with engine.connect() as db:
        assert query(db,"SELECT count(*) FROM staging.voice_events WHERE intent_id=:id AND kind='recording.archived' AND details->>'recording_sid'=:sid",id=recovered_job.intent_id,sid=recovered_job.recording_sid).scalar_one()==1
    for statement in ['DELETE FROM staging.voice_archive_jobs','DELETE FROM staging.voice_intents','DELETE FROM staging.voice_recordings',
                      'UPDATE staging.voice_events SET kind=kind','DELETE FROM staging.voice_events','TRUNCATE staging.voice_events']:
        try:
            with engine.begin() as db:
                query(db,statement)
        except DBAPIError as error:
            assert error.orig.sqlstate=='42501'
        else:
            raise AssertionError('Voice history permissions are too broad')
    print('Voice HTTP/PG: authorization, signed callbacks, recovery races, durable private recording archive, cursor history and protected audio playback: PASS')
finally:
    server.should_exit=True
    thread.join(5)
    engine.dispose()

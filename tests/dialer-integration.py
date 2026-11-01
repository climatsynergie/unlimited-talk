"""Automatic dialer and caller-ID integration with real HTTP/PG, no provider network."""
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
from uuid import UUID,uuid4
from xml.etree import ElementTree

from sqlalchemy.exc import DBAPIError
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator
import uvicorn

from app.database import make_engine
from app.identity.security import COOKIE, CSRF_COOKIE, digest, new_token
from app.identity.service import query
from app.main import app, lifespan
from app.telephony.twilio_voice import ControlledVoiceProfile, ManualVoiceProfile, client_identity, webhook_url

assert os.environ['DB_HOST'] == 'db' and os.environ.get('DB_DEPLOYMENT', 'local') == 'local'
assert os.environ['COMMUNICATIONS_MODE'] == 'disabled'
engine = make_engine()
with engine.connect() as db:
    assert query(db, "SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one() == 'synthetic_only'

profile = ManualVoiceProfile('AC'+uuid4().hex, 'SK'+'b'*32, 'c'*32, 'AP'+'d'*32,
    'webhooks_sharedkey_'+'e'*26, 'f'*32, 'https://voice.example.invalid', '+15145550100', 3, 600)
base = 'http://127.0.0.1:18002'
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
server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=18002, log_level='critical', access_log=False))
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


from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from app.telephony import caller_directory,completion

class Inventory:
    def read(self):
        assert engine.pool.checkedout()==0
        return [dict(provider_sid='PN'+'1'*32,number=profile.caller_number,name='Montréal',country='CA',voice_enabled=True),
                dict(provider_sid='PN'+'2'*32,number='+14165550200',name='Toronto',country='CA',voice_enabled=True),
                dict(provider_sid='PN'+'3'*32,number='+442079460002',name='Royaume-Uni',country='GB',voice_enabled=True)]

group=f'{20000+uuid4().int%60000:05d}'
def destination(slot):return '+1416'+group+f'{slot:02d}'
uk_destination='+44207946'+str(1000+uuid4().int%8000)

def all_hours():return [dict(weekday=i,start=0,end=1440) for i in range(7)]
def config(campaign,number,hours=None,rules=None,expected=200):
    current=admin.request('GET','/api/telephony/campaigns/'+campaign['id']+'/calling')['settings']
    return admin.request('PUT','/api/telephony/campaigns/'+campaign['id']+'/calling',dict(request_id=str(uuid4()),
        version=current['version'],enabled=True,default_number_id=number,hours=hours or all_hours(),rules=rules or []),expected)
def card(campaign,contact):return admin.request('GET','/api/campaigns/'+campaign['id']+'/contacts/'+str(contact))['contact']
def seed(campaign,phone):
    identifier=uuid4()
    with engine.begin() as db:
        query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,'{\"display_name\":\"Contact composeur\"}')",id=identifier,phone=phone)
    enroll(campaign,identifier)
    return identifier
def enroll(campaign,contact):
    admin.request('POST','/api/campaigns/'+campaign['id']+'/contacts',dict(request_id=str(uuid4()),contact_ids=[str(contact)]))
def schedule(agent,campaign,contact):
    future=(datetime.now(timezone.utc)+timedelta(days=1)).replace(second=0,microsecond=0)
    identifier=uuid4()
    agent.request('POST','/api/callbacks',dict(id=str(identifier),campaign_id=campaign['id'],contact_id=str(contact),
        membership_version=card(campaign,contact)['version'],local_start=future.replace(tzinfo=None).isoformat(),timezone='UTC',notes='Rappel du composeur'),201)
    return identifier
def start(agent,browser,campaign):
    return agent.request('POST','/api/telephony/dialer/control',dict(action='start',browser_id=str(browser),campaign_id=campaign['id']))['dialer']
def next_call(agent,browser,state,identifier=None,expected=200):
    return agent.request('POST','/api/telephony/dialer/next',dict(id=str(identifier or uuid4()),browser_id=str(browser),generation=state['generation']),expected)
def finish(agent,identifier,outcome='completed'):
    current=row(identifier)
    if current['state']=='reserved':parent,xml=voice(agent,identifier)
    else:parent=current['parent_call_sid']
    current=row(identifier);child=current['child_call_sid'] or 'CA'+uuid4().hex
    signed('status',identifier,dict(CallSid=child,ParentCallSid=parent,From=current['caller_number'],To=current['destination'],
        CallStatus='in-progress',SequenceNumber='1'))
    signed('finish',identifier,dict(CallSid=parent,DialCallSid=child,DialCallStatus=outcome))
    with engine.begin() as db:query(db,"UPDATE staging.voice_completion_jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE intent_id=:id",id=identifier)
    completion.process_once(engine,profile)

try:
    admin=Browser();agents=[Browser('agent') for _ in range(3)]
    a=admin.request('POST','/api/campaigns',dict(name='Composeur A '+uuid4().hex,timezone='UTC'),201)
    b=admin.request('POST','/api/campaigns',dict(name='Composeur B '+uuid4().hex,timezone='Europe/London'),201)
    for campaign in [a,b]:
        for agent in agents:admin.request('PUT','/api/campaigns/'+campaign['id']+'/agents/'+str(agent.id),dict(is_active=True))
    assert caller_directory.synchronize_once(engine,profile,Inventory())=='synchronized'
    directory=admin.request('GET','/api/telephony/numbers')['items']
    numbers={item['number']:item['id'] for item in directory}
    assert len(numbers)==3
    agents[0].request('GET','/api/telephony/numbers',expected=403)
    rule=dict(number_id=numbers[profile.caller_number],country='CA',prefix='+1416')
    config(a,numbers['+14165550200'],rules=[rule,dict(number_id=numbers['+442079460002'],country='GB',prefix='')])
    config(b,numbers['+442079460002'])
    current=admin.request('GET','/api/telephony/campaigns/'+a['id']+'/calling')['settings']
    # Retrying a saved configuration after a lost HTTP response returns the
    # original response shape and does not increment its optimistic version.
    saved_request={**current,'request_id':str(uuid4())}
    saved=admin.request('PUT','/api/telephony/campaigns/'+a['id']+'/calling',saved_request)
    assert admin.request('PUT','/api/telephony/campaigns/'+a['id']+'/calling',saved_request)==saved
    admin.request('PUT','/api/telephony/campaigns/'+a['id']+'/calling',{**saved_request,'enabled':False},409)
    current=saved['settings']
    agents[0].request('PUT','/api/telephony/campaigns/'+a['id']+'/calling',dict(request_id=str(uuid4()),version=current['version'],enabled=True,
        default_number_id=numbers['+14165550200'],hours=all_hours(),rules=[]),403)
    config(a,str(uuid4()),expected=409)
    # A country rule routes UK destinations through an owned UK caller.
    uk=seed(a,uk_destination)
    manual=agents[0].request('POST','/api/telephony/test/intents',dict(id=str(uuid4()),destination=uk_destination,campaign_id=a['id']),201)
    assert manual['intent']['caller_number']=='+442079460002'
    agents[0].request('POST','/api/telephony/test/intents/'+manual['intent']['id']+'/cancel',{})
    admin.request('POST','/api/campaigns/'+a['id']+'/contacts/'+str(uk)+'/remove',
        dict(request_id=str(uuid4()),version=card(a,uk)['version']))
    # Pending callbacks reserve a contact across campaign queues and owners.
    due=seed(b,destination(1));enroll(a,due)
    callback=schedule(agents[0],b,due)
    with engine.begin() as db:query(db,"UPDATE staging.callbacks SET due_at=clock_timestamp()-interval '1 minute' WHERE id=:id",id=callback)
    future_contact=seed(a,destination(2));enroll(b,future_contact)
    future_callback=schedule(agents[1],b,future_contact)
    agents[0].request('POST','/api/telephony/test/intents',dict(id=str(uuid4()),destination=destination(2),campaign_id=a['id']),409)
    ordinary=[seed(a,destination(i)) for i in range(10,18)]
    # The due callback's campaign remains authoritative, even while the agent's
    # selected ordinary campaign is outside its own configured calling hours.
    tomorrow_weekday=(datetime.now(timezone.utc).weekday()+1)%7
    config(a,numbers['+14165550200'],hours=[dict(weekday=tomorrow_weekday,start=0,end=1440)],rules=[rule])
    browser=uuid4();state=start(agents[0],browser,a)
    wanted=uuid4();first=next_call(agents[0],browser,state,wanted)
    assert first['intent']['callback_id']==str(callback) and first['intent']['campaign_id']==b['id']
    assert first['intent']['caller_number']=='+442079460002'
    assert next_call(agents[0],browser,state,wanted)['intent']['id']==str(wanted)
    parent,xml=voice(agents[0],wanted)
    assert xml.find('Dial').get('callerId')=='+442079460002'
    signed('parent-status',fields=dict(CallSid=parent,CallStatus='completed'))
    assert row(wanted)['state']=='authorized', 'Parent alone cannot release an unobserved child'
    assert next_call(agents[0],browser,state)['idle']=='active_call'
    finish(agents[0],wanted)
    assert agents[0].request('GET','/api/callbacks/'+str(callback))['callback']['status']=='completed'
    assert next_call(agents[0],browser,state).get('intent') is None
    config(a,numbers['+14165550200'],rules=[rule])
    prepared=next_call(agents[0],browser,state)
    identifier=UUID(prepared['intent']['id'])
    assert prepared['intent']['caller_number']==profile.caller_number and prepared['intent']['contact_id']!=str(future_contact)
    paused=agents[0].request('POST','/api/telephony/dialer/control',dict(action='pause',browser_id=str(browser),generation=state['generation']))['dialer']
    assert voice(agents[0],identifier)[1].find('Dial') is None and row(identifier)['consumed_at'] is None
    next_call(agents[0],browser,state,expected=409)
    state=start(agents[0],browser,a)
    # Pause and signed consumption contend on the same actor/run reservation.
    prepared=next_call(agents[0],browser,state);identifier=UUID(prepared['intent']['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1=pool.submit(lambda:voice(agents[0],identifier))
        f2=pool.submit(lambda:agents[0].request('POST','/api/telephony/dialer/control',dict(action='pause',browser_id=str(browser),generation=state['generation'])))
        _,xml=f1.result();f2.result()
    assert row(identifier)['state'] in {'cancelled','authorized'}
    if xml.find('Dial') is not None:finish(agents[0],identifier,'no-answer')
    # Three agent controllers claim three different contacts atomically.
    browsers=[uuid4() for _ in agents]
    states=[start(agent,browsers[i],a) for i,agent in enumerate(agents)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        calls=list(pool.map(lambda i:next_call(agents[i],browsers[i],states[i]),range(3)))
    assert len({call['intent']['destination'] for call in calls})==3
    assert all(call['intent']['callback_id'] is None for call in calls)
    for i,call in enumerate(calls):
        identifier=UUID(call['intent']['id']);parent,xml=voice(agents[i],identifier)
        current=row(identifier)
        assert xml.find('Dial').get('callerId')==current['caller_number']
        if i==0:
            # Appointment entry holds progression AND completion, so a form's
            # membership version cannot be overwritten underneath its user.
            token=uuid4()
            hold=agents[i].request('POST','/api/telephony/dialer/control',dict(action='hold',browser_id=str(browsers[i]),
                generation=states[i]['generation'],hold_token=str(token),campaign_id=a['id']))['dialer']
            before=card(a,current['contact_id'])
            finish(agents[i],identifier)
            assert card(a,current['contact_id'])['version']==before['version']
            agents[i].request('POST','/api/telephony/dialer/heartbeat',dict(browser_id=str(browsers[i]),generation=hold['generation']))
            due_date=(datetime.now(timezone.utc)+timedelta(days=2)).replace(second=0,microsecond=0)
            agents[i].request('POST','/api/calendar',dict(id=str(uuid4()),campaign_id=a['id'],contact_id=str(current['contact_id']),
                membership_version=before['version'],local_start=due_date.replace(tzinfo=None).isoformat(),timezone='UTC',duration_minutes=30,notes='RDV pendant appel'),201)
            states[i]=agents[i].request('POST','/api/telephony/dialer/control',dict(action='release',browser_id=str(browsers[i]),generation=hold['generation'],hold_token=str(token)))['dialer']
            completion.process_once(engine,profile)
            with engine.connect() as db:
                kind=query(db,'''SELECT s.kind FROM staging.campaign_contacts m JOIN staging.campaign_stages s ON s.id=m.stage_id
                    WHERE m.campaign_id=:campaign AND m.contact_id=:contact''',campaign=a['id'],contact=current['contact_id']).scalar_one()
            assert kind=='appointment'
        else:finish(agents[i],identifier,'no-answer' if i==1 else 'completed')
    # A stale presence lease cannot grant the next call or consume a reserved one.
    prepared=next_call(agents[1],browsers[1],states[1]);identifier=UUID(prepared['intent']['id'])
    with engine.begin() as db:query(db,"UPDATE staging.voice_dialer_sessions SET lease_until=clock_timestamp()-interval '1 second' WHERE actor_id=:id",id=agents[1].id)
    assert voice(agents[1],identifier)[1].find('Dial') is None
    assert next_call(agents[1],browsers[1],states[1])['idle']=='presence_expired'
    # Global cooldown and daily quota survive campaign switches.
    quota_zone='Etc/GMT+12' if datetime.now(timezone.utc).hour<12 else 'UTC'
    quota=admin.request('POST','/api/campaigns',dict(name='Quota '+uuid4().hex,timezone=quota_zone),201)
    admin.request('PUT','/api/campaigns/'+quota['id']+'/agents/'+str(agents[1].id),dict(is_active=True))
    config(quota,numbers['+14165550200'])
    q=seed(quota,destination(90));enroll(b,q)
    first_id=uuid4()
    agents[1].request('POST','/api/telephony/test/intents',dict(id=str(first_id),destination=destination(90),campaign_id=quota['id']),201)
    finish(agents[1],first_id)
    agents[1].request('POST','/api/telephony/test/intents',dict(id=str(uuid4()),destination=destination(90),campaign_id=b['id']),409)
    with engine.begin() as db:query(db,"UPDATE staging.voice_intents SET consumed_at=clock_timestamp()-interval '3 hours' WHERE id=:id",id=first_id)
    second_id=uuid4()
    agents[1].request('POST','/api/telephony/test/intents',dict(id=str(second_id),destination=destination(90),campaign_id=b['id']),201)
    finish(agents[1],second_id)
    agents[1].request('POST','/api/telephony/test/intents',dict(id=str(uuid4()),destination=destination(90),campaign_id=quota['id']),409)
    # A callback rescheduled during the actual call keeps its pending date and
    # callback stage; a late result cannot mark that new schedule completed.
    changed=seed(b,destination(80));changed_callback=schedule(agents[2],b,changed)
    with engine.begin() as db:query(db,"UPDATE staging.callbacks SET due_at=clock_timestamp()-interval '1 minute' WHERE id=:id",id=changed_callback)
    changing_id=uuid4()
    agents[2].request('POST','/api/telephony/test/intents',dict(id=str(changing_id),destination=destination(80),campaign_id=b['id']),201)
    voice(agents[2],changing_id)
    future=(datetime.now(timezone.utc)+timedelta(days=3)).replace(second=0,microsecond=0)
    cb=agents[2].request('GET','/api/callbacks/'+str(changed_callback))['callback']
    agents[2].request('PATCH','/api/callbacks/'+str(changed_callback),dict(version=cb['version'],status='scheduled',
        local_start=future.replace(tzinfo=None).isoformat(),timezone='UTC',notes='Nouvelle date pendant appel'))
    before_changed=card(b,changed);finish(agents[2],changing_id)
    assert card(b,changed)['stage_id']==before_changed['stage_id']
    assert agents[2].request('GET','/api/callbacks/'+str(changed_callback))['callback']['status']=='scheduled'
    # A later higher-ranked provider result cannot overwrite a human's newer
    # pipeline decision, and call history remains single and immutable.
    late_contact=seed(a,destination(81));late_id=uuid4()
    agents[2].request('POST','/api/telephony/test/intents',dict(id=str(late_id),destination=destination(81),campaign_id=a['id']),201)
    late_parent,_=voice(agents[2],late_id);current=row(late_id);late_child='CA'+uuid4().hex
    signed('status',late_id,dict(CallSid=late_child,ParentCallSid=late_parent,From=current['caller_number'],To=current['destination'],CallStatus='busy',SequenceNumber='1'))
    with engine.begin() as db:query(db,"UPDATE staging.voice_completion_jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE intent_id=:id",id=late_id)
    completion.process_once(engine,profile)
    chosen=admin.request('POST','/api/campaigns/'+a['id']+'/stages',dict(name='Choix manuel '+uuid4().hex,color='blue'),201)
    current_card=card(a,late_contact)
    agents[2].request('POST','/api/campaigns/'+a['id']+'/contacts/'+str(late_contact)+'/move',dict(request_id=str(uuid4()),stage_id=chosen['id'],version=current_card['version']))
    manual_card=card(a,late_contact)
    signed('finish',late_id,dict(CallSid=late_parent,DialCallSid=late_child,DialCallStatus='completed'))
    with engine.begin() as db:query(db,"UPDATE staging.voice_completion_jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE intent_id=:id",id=late_id)
    completion.process_once(engine,profile)
    assert card(a,late_contact)['stage_id']==manual_card['stage_id'] and card(a,late_contact)['version']==manual_card['version']
    with engine.connect() as db:
        assert query(db,"SELECT count(*) FROM staging.campaign_events WHERE action='call.finished' AND details->>'intent_id'=:id",id=str(late_id)).scalar_one()==1
    # Repeated outcomes still return a contact to the end of the queue, even
    # when its pipeline stage already is "no answer".
    requeued=seed(a,destination(83))
    with engine.begin() as db:
        query(db,"UPDATE staging.campaign_contacts SET stage_id=(SELECT id FROM staging.campaign_stages WHERE campaign_id=:campaign AND kind='no_answer') WHERE campaign_id=:campaign AND contact_id=:contact",campaign=a['id'],contact=requeued)
    before_requeue=card(a,requeued)
    seed(a,destination(84))
    requeue_id=uuid4()
    agents[2].request('POST','/api/telephony/test/intents',dict(id=str(requeue_id),destination=destination(83),campaign_id=a['id']),201)
    finish(agents[2],requeue_id,'no-answer')
    after_requeue=card(a,requeued)
    assert after_requeue['stage_id']==before_requeue['stage_id'] and after_requeue['queue_position']>before_requeue['queue_position']
    # An abandoned booking form must not strand terminal calls indefinitely.
    abandoned=seed(a,destination(86));abandoned_id=uuid4()
    agents[2].request('POST','/api/telephony/test/intents',dict(id=str(abandoned_id),destination=destination(86),campaign_id=a['id']),201)
    voice(agents[2],abandoned_id)
    agents[2].request('POST','/api/telephony/dialer/control',dict(action='hold',browser_id=str(browsers[2]),generation=states[2]['generation'],hold_token=str(uuid4()),campaign_id=a['id']))
    finish(agents[2],abandoned_id)
    assert row(abandoned_id)['settled_at'] is None
    with engine.begin() as db:query(db,"UPDATE staging.voice_dialer_sessions SET lease_until=clock_timestamp()-interval '1 second' WHERE actor_id=:id",id=agents[2].id)
    completion.process_once(engine,profile)
    assert row(abandoned_id)['settled_at'] is not None
    assert agents[2].request('GET','/api/telephony/dialer/session')['dialer']['mode']=='paused'
    # Historical caller identities survive inventory changes. New selections of
    # a missing number are blocked instead of silently substituting another one.
    unknown=destination(82);unknown_id=uuid4()
    agents[2].request('POST','/api/telephony/test/intents',dict(id=str(unknown_id),destination=unknown),201)
    with engine.begin() as db:
        query(db,"INSERT INTO staging.contacts(id,phone,profile,do_not_contact) VALUES (:id,:phone,'{}',true)",id=uuid4(),phone=unknown)
    assert voice(agents[2],unknown_id)[1].find('Dial') is None and row(unknown_id)['consumed_at'] is None
    with engine.begin() as db:
        query(db,'UPDATE staging.voice_numbers SET is_present=false WHERE id=:id',id=numbers['+442079460002'])
    config(b,numbers['+442079460002'],expected=409)
    assert row(first_id)['caller_number']=='+14165550200' and row(second_id)['caller_number']=='+442079460002'
    # A regional number becoming unavailable must not starve later eligible
    # contacts beyond the first SQL batch of one hundred.
    batch=admin.request('POST','/api/campaigns',dict(name='File longue '+uuid4().hex,timezone='America/Toronto'),201)
    admin.request('PUT','/api/campaigns/'+batch['id']+'/agents/'+str(agents[0].id),dict(is_active=True))
    with engine.begin() as db:query(db,'UPDATE staging.voice_numbers SET is_present=true WHERE id=:id',id=numbers['+442079460002'])
    config(batch,numbers['+14165550200'],rules=[dict(country='GB',prefix='',number_id=numbers['+442079460002'])])
    batch_ids=[];phone_prefix='+442079'+f'{uuid4().int%400:03d}'
    with engine.begin() as db:
        for index in range(101):
            contact_id=uuid4();batch_ids.append(str(contact_id))
            query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,'{}')",id=contact_id,phone=phone_prefix+f'{index:03d}')
    admin.request('POST','/api/campaigns/'+batch['id']+'/contacts',dict(request_id=str(uuid4()),contact_ids=batch_ids))
    eligible=seed(batch,destination(85))
    with engine.begin() as db:query(db,'UPDATE staging.voice_numbers SET is_present=false WHERE id=:id',id=numbers['+442079460002'])
    batch_browser=browsers[0];batch_state=start(agents[0],batch_browser,batch)
    batch_call=next_call(agents[0],batch_browser,batch_state)
    assert batch_call['intent']['contact_id']==str(eligible)
    agents[0].request('POST','/api/telephony/dialer/control',dict(action='stop',browser_id=str(batch_browser),generation=batch_state['generation']))
    print('Dialer HTTP/PG: due callback ownership/priority, regional owned callers, three parallel claims, pause/consume race, booking holds, lease expiry and global attempt limits: PASS')
finally:
    server.should_exit=True;thread.join(5);engine.dispose()

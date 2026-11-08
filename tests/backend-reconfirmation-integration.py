"""Isolated HTTP/PG regressions for reconfirmations and callback-safe language handoff.

No provider requests, calls, SMS, environment changes, or production database.
"""
import json,os,unittest,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from app.database import make_engine
from app.identity.security import COOKIE,CSRF_COOKIE,new_token,digest,encryption_key
from app.identity.service import query

assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
assert os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:
    assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
origin=os.environ['APP_ORIGIN']
base='http://127.0.0.1:8000'
cipher=encryption_key(os.environ['IDENTITY_KEY_FILE'])

class Browser:
    def __init__(self,role):
        self.id=uuid4();self.token=new_token();self.csrf=new_token()
        with engine.begin() as db:
            query(db,'''INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret)
                VALUES (:id,:email,'QA reconfirmation',:role,'unused',:mfa)''',id=self.id,email=str(self.id)+'@example.invalid',role=role,
                mfa=cipher.encrypt(b'JBSWY3DPEHPK3PXP').decode() if role=='admin' else None)
            query(db,'''INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at)
                VALUES (:token,:csrf,:actor,true,clock_timestamp()+interval '1 hour')''',token=digest(self.token),csrf=digest(self.csrf),actor=self.id)
    def request(self,method,path,body=None,expected=200):
        headers={'Cookie':COOKIE+'='+self.token+'; '+CSRF_COOKIE+'='+self.csrf,'Origin':origin,'X-CSRF-Token':self.csrf,'Content-Type':'application/json'}
        request=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:response=urllib.request.urlopen(request,timeout=20)
        except urllib.error.HTTPError as error:response=error
        with response:
            result=json.loads(response.read())
            if response.status!=expected:raise AssertionError((method,path,response.status,expected,result))
            return result

class BackendReconfirmationTests(unittest.TestCase):
    def setUp(self):
        self.admin=Browser('admin');self.agent=Browser('agent')
        self.campaign=self.admin.request('POST','/api/campaigns',dict(name='QA reconfirmation '+uuid4().hex),201)
        self.path='/api/campaigns/'+self.campaign['id']
        self.admin.request('PUT',self.path+'/agents/'+str(self.agent.id),dict(is_active=True))
        self.contact=uuid4()
        with engine.begin() as db:
            for _ in range(100):
                phone='+1613555'+f'{uuid4().int%10000:04d}'
                if query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,'{}') ON CONFLICT(phone) DO NOTHING RETURNING id",id=self.contact,phone=phone).first():break
            else:raise AssertionError('Synthetic phone fixture range exhausted')
        self.contact_path=self.path+'/contacts/'+str(self.contact)
        self.admin.request('POST',self.path+'/contacts',dict(request_id=str(uuid4()),contact_ids=[str(self.contact)]))
        self.stages={stage['kind']:stage for stage in self.admin.request('GET',self.path+'/board')['stages']}
        self.schedule=dict(local_start=(datetime.now(timezone.utc).replace(tzinfo=None,second=0,microsecond=0)+timedelta(days=3)).isoformat(),
            timezone='UTC',utc_offset_minutes=0,duration_minutes=30,notes='QA reconfirmation')
    def card(self):return self.admin.request('GET',self.contact_path)['contact']
    def book(self,status='cancelled'):
        current=self.admin.request('GET',self.contact_path)['qualification']
        row=self.agent.request('POST','/api/calendar',dict(id=str(uuid4()),campaign_id=self.campaign['id'],contact_id=str(self.contact),
            membership_version=self.card()['version'],qualification=QUALIFICATION,qualification_revision=current['revision'] if current else None,**self.schedule),201)
        if status!='booked':row=self.agent.request('PATCH','/api/calendar/'+row['id'],dict(version=row['version'],status=status,**self.schedule))
        return row
    def change_stage(self,kind):
        self.admin.request('POST',self.contact_path+'/move',dict(request_id=str(uuid4()),version=self.card()['version'],stage_id=self.stages[kind]['id']))
    def callback(self):
        identifier=str(uuid4())
        result=self.agent.request('POST','/api/callbacks',dict(id=identifier,campaign_id=self.campaign['id'],contact_id=str(self.contact),membership_version=self.card()['version'],
            local_start=(datetime.now(timezone.utc).replace(tzinfo=None,second=0,microsecond=0)+timedelta(days=2)).isoformat(),timezone='UTC',utc_offset_minutes=0,notes='Promesse de rappel'),201)
        return result
    def reconfirm(self,row,expected=200):
        return self.agent.request('PATCH','/api/calendar/'+row['id'],dict(version=row['version'],status='booked',**self.schedule),expected)
    def test_reconfirmation_restores_pipeline_and_closes_callback(self):
        row=self.book();callback=self.callback()
        self.reconfirm(row)
        self.assertEqual(self.card()['stage_id'],self.stages['appointment']['id'])
        self.assertEqual(self.agent.request('GET','/api/callbacks/'+callback['id'])['callback']['status'],'cancelled')
    def test_reconfirmation_of_completed_and_absent_visits_syncs_pipeline(self):
        for status in ('completed','no_show'):
            with self.subTest(status=status):
                row=self.book(status);self.change_stage('other');self.reconfirm(row)
                self.assertEqual(self.card()['stage_id'],self.stages['appointment']['id'])
    def assert_restriction_reconfirmation_rejected(self,kind):
        row=self.book();path='/api/calendar/'+row['id']
        self.change_stage(kind)
        before=self.admin.request('GET',path)
        self.reconfirm(row,409)
        after=self.admin.request('GET',path)
        self.assertEqual(after['appointment']['status'],'cancelled')
        self.assertEqual(after['appointment']['version'],before['appointment']['version'])
        self.assertEqual(after['events'],before['events'])
    def test_reconfirmation_cannot_bypass_non_interested(self):
        self.assert_restriction_reconfirmation_rejected('non_interested')
    def test_reconfirmation_cannot_bypass_do_not_contact(self):
        self.assert_restriction_reconfirmation_rejected('do_not_contact')
    def test_reconfirmation_checks_assignment(self):
        row=self.book();self.admin.request('PUT',self.path+'/agents/'+str(self.agent.id),dict(is_active=False))
        self.reconfirm(row,403)
    def test_reconfirmation_checks_membership(self):
        row=self.book()
        self.admin.request('POST',self.contact_path+'/remove',dict(request_id=str(uuid4()),version=self.card()['version']))
        self.reconfirm(row,404)
    def test_reconfirmation_checks_archived_campaign(self):
        row=self.book()
        self.admin.request('PATCH',self.path,{k:self.campaign[k] for k in ('name','description','timezone','version')}|dict(is_active=False))
        self.reconfirm(row,403)
    def test_existing_booked_edit_rights_survive_campaign_unassignment(self):
        row=self.book('booked');self.admin.request('PUT',self.path+'/agents/'+str(self.agent.id),dict(is_active=False))
        edited=self.agent.request('PATCH','/api/calendar/'+row['id'],dict(version=row['version'],status='booked',**{**self.schedule,'notes':'Historical creator edit retained'}))
        self.assertEqual(edited['notes'],'Historical creator edit retained')
    def test_reconfirmation_concurrent_editors_commit_one_transition(self):
        row=self.book();callback=self.callback()
        body=dict(version=row['version'],status='booked',**self.schedule)
        def patch(actor):
            try:
                actor.request('PATCH','/api/calendar/'+row['id'],body)
                return 200
            except AssertionError as error:
                self.assertEqual(error.args[0][2],409)
                return 409
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(patch,[self.admin,self.agent])),[200,409])
        result=self.admin.request('GET','/api/calendar/'+row['id'])
        self.assertEqual(result['appointment']['version'],row['version']+1)
        self.assertEqual(self.agent.request('GET','/api/callbacks/'+callback['id'])['callback']['status'],'cancelled')
    def test_existing_cancelled_notes_remain_editable_after_unassignment(self):
        row=self.book();self.admin.request('PUT',self.path+'/agents/'+str(self.agent.id),dict(is_active=False))
        result=self.agent.request('PATCH','/api/calendar/'+row['id'],dict(version=row['version'],status='cancelled',**{**self.schedule,'notes':'Historical cancelled notes retained'}))
        self.assertEqual(result['notes'],'Historical cancelled notes retained')
    def test_unqualified_legacy_reconfirmation_requires_qualification_for_all_statuses(self):
        for status in ('cancelled','completed','no_show'):
            with self.subTest(status=status):
                identifier=uuid4()
                with engine.begin() as db:
                    query(db,'''INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone,status)
                        VALUES (:id,:campaign,:contact,:actor,'qa-legacy',clock_timestamp(),clock_timestamp()+interval '30 minutes','UTC',:status)''',
                        id=identifier,campaign=self.campaign['id'],contact=self.contact,actor=self.agent.id,status=status)
                self.reconfirm(dict(id=str(identifier),version=0),422)
    def test_due_callback_language_transfer_is_rejected_without_losing_the_promise(self):
        callback=self.callback()
        with engine.begin() as db:query(db,"UPDATE staging.callbacks SET due_at=clock_timestamp()-interval '1 minute' WHERE id=:id",id=callback['id'])
        before=self.agent.request('GET','/api/callbacks/'+callback['id'])['callback']
        card=self.card()
        self.agent.request('POST',self.contact_path+'/english',dict(request_id=str(uuid4()),version=card['version']),409)
        after=self.agent.request('GET','/api/callbacks/'+callback['id'])['callback']
        self.assertEqual(after,before)
        self.assertEqual(self.card(),card)
    def test_future_callback_language_transfer_remains_rejected(self):
        callback=self.callback();card=self.card()
        self.agent.request('POST',self.contact_path+'/english',dict(request_id=str(uuid4()),version=card['version']),409)
        self.assertEqual(self.agent.request('GET','/api/callbacks/'+callback['id'])['callback']['status'],'scheduled')
    def test_language_transfer_without_callback_still_succeeds_once(self):
        body=dict(request_id=str(uuid4()),version=self.card()['version'])
        first=self.agent.request('POST',self.contact_path+'/english',body)
        self.assertEqual(self.agent.request('POST',self.contact_path+'/english',body),first)
        self.assertEqual(self.card()['profile']['preferred_language'],'en')

try:
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BackendReconfirmationTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
finally:engine.dispose()

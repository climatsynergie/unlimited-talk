"""Transaction-rolled-back PostgreSQL/XLSX regressions; never contacts providers."""
import os,unittest
from datetime import datetime,timezone
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4
from openpyxl import load_workbook
from app.database import make_engine
from app.identity.service import query
from app.reporting.service import report,live,Period
from app.reporting.excel import workbook
assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
assert os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:
 assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'

class IncomingReportingTests(unittest.TestCase):
 def setUp(self):
  self.db=engine.connect();self.transaction=self.db.begin()
  self.actor,self.queue,self.registration=(uuid4() for _ in range(3))
  self.day=datetime.now(timezone.utc).date();self.period=Period(self.day,self.day,'UTC')
  query(self.db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'QA inbound report','admin','unused')",id=self.actor,email=str(self.actor)+'@example.invalid')
  for _ in range(100):
   phone='+1613555'+f'{uuid4().int%10000:04d}'
   if not query(self.db,'SELECT 1 FROM staging.inbound_queues WHERE phone=:phone',phone=phone).first():break
  else:raise AssertionError('Synthetic queue phones exhausted')
  query(self.db,"INSERT INTO staging.inbound_queues(id,name,phone,timezone,created_by) VALUES (:id,:name,:phone,'UTC',:actor)",id=self.queue,name='QA inbound report '+uuid4().hex,phone=phone,actor=self.actor)
  query(self.db,"INSERT INTO staging.inbound_registrations(id,actor_id,session_hash,browser_id,available,media_ready,lease_until) VALUES (:id,:actor,:hash,:browser,true,true,clock_timestamp()+interval '90 seconds')",id=self.registration,actor=self.actor,hash='a'*64,browser=uuid4())
 def tearDown(self):
  self.transaction.rollback();self.db.close()
 def offer(self,connected=True,duration=60,active=False,recording=None):
  call,offer=uuid4(),uuid4()
  query(self.db,"""INSERT INTO staging.inbound_calls(id,queue_id,account_sid,parent_call_sid,caller_number,called_number,caller_fingerprint,state,outcome,agent_id,received_at,connected_at,finished_at)
   VALUES (:id,:queue,:account,:sid,'+14165550101','+14165550102',:hash,:state,:outcome,:actor,clock_timestamp()-interval '2 minutes',CASE WHEN :connected THEN clock_timestamp()-interval '1 minute' END,CASE WHEN :active THEN NULL ELSE clock_timestamp() END)""",id=call,queue=self.queue,account='AC'+uuid4().hex,sid='CA'+uuid4().hex,hash=uuid4().hex*2,state='connected' if active else 'finished',outcome='answered' if connected else 'missed',actor=self.actor,connected=connected,active=active)
  query(self.db,"""INSERT INTO staging.inbound_offers(id,call_id,actor_id,registration_id,session_hash,client_identity,state,offered_at,connected_at,ended_at,outcome,duration_seconds)
   VALUES (:id,:call,:actor,:registration,:hash,:identity,:state,clock_timestamp()-interval '2 minutes',CASE WHEN :connected THEN clock_timestamp()-interval '1 minute' END,CASE WHEN :active THEN NULL ELSE clock_timestamp() END,:outcome,:duration)""",id=offer,call=call,actor=self.actor,registration=self.registration,hash='a'*64,identity='ut_in_'+uuid4().hex,state='connected' if active else 'finished',connected=connected,active=active,outcome='completed' if connected else 'no-answer',duration=duration)
  if recording is not None:
   query(self.db,"""INSERT INTO staging.inbound_recordings(sid,call_id,offer_id,call_sid,kind,duration,channels)
    VALUES (:sid,:call,:offer,:child,'conversation',:duration,2)""",sid='RE'+uuid4().hex,call=call,offer=offer,child='CA'+uuid4().hex,duration=recording)
  return offer
 def metrics(self):return report(self.db,self.period,self.actor)
 def test_incoming_counts_are_separate_in_all_grains_and_excel(self):
  self.offer(duration=60);self.offer(connected=False,duration=0)
  result=self.metrics()
  for row in (result['totals'],result['agents'][0]['metrics'],result['daily'][0]):
   self.assertEqual((row.get('incoming_calls',0),row.get('incoming_answered',0),row.get('incoming_talk_seconds',0)),(2,1,60))
   self.assertEqual((row['calls'],row['answered'],row['talk_seconds']),(0,0,0))
   self.assertIsNone(row['answer_rate'])
  self.assertEqual(sum(row.get('incoming_calls',0) for row in result['hourly']),2)
  self.assertEqual(sum(row.get('incoming_talk_seconds',0) for row in result['hourly']),60)
  book=load_workbook(BytesIO(workbook(result)),read_only=True)
  for name in ('Synthèse','Par jour','Par heure'):
   rows=list(book[name].values);head=rows[0]
   self.assertIn('Appels entrants proposés',head)
   self.assertEqual(sum(row[head.index('Appels entrants proposés')] for row in rows[1:]),2)
 def test_incoming_only_admin_is_in_team_roster(self):
  self.offer()
  result=report(self.db,self.period)
  row=next((row for row in result['agents'] if row['id']==self.actor),None)
  self.assertIsNotNone(row)
  self.assertEqual(row['metrics'].get('incoming_calls',0),1)
 def test_incoming_only_admin_with_active_offer_is_visible_live(self):
  identifier=self.offer(active=True)
  row=next((row for row in live(self.db)['items'] if row['id']==self.actor),None)
  self.assertIsNotNone(row)
  self.assertEqual((row['direction'],row['status'],row['call_id']),('incoming','connected',identifier))
 def test_duration_uses_provider_then_recording_and_does_not_invent_missing(self):
  self.offer(duration=60,recording=75);self.offer(duration=None,recording=45);self.offer(duration=None)
  row=self.metrics()['totals']
  self.assertEqual((row.get('incoming_calls',0),row.get('incoming_answered',0),row.get('incoming_talk_seconds',0)),(3,3,105))
 def test_schema_eleven_compatibility_zeros_without_incoming_query(self):
  self.offer()
  with patch('app.telephony.incoming_schema.installed',return_value=False):
   row=self.metrics()['totals']
   self.assertEqual((row.get('incoming_calls',0),row.get('incoming_answered',0),row.get('incoming_talk_seconds',0)),(0,0,0))
   self.assertNotIn(self.actor,[row['id'] for row in live(self.db)['items']])
 def test_duplicate_conversation_recordings_do_not_multiply_offers(self):
  offer=self.offer(duration=None,recording=40)
  with self.db.begin_nested():
   call=query(self.db,'SELECT call_id FROM staging.inbound_offers WHERE id=:id',id=offer).scalar_one()
   query(self.db,"INSERT INTO staging.inbound_recordings(sid,call_id,offer_id,call_sid,kind,duration,channels) VALUES (:sid,:call,:offer,:child,'conversation',45,2)",sid='RE'+uuid4().hex,call=call,offer=offer,child='CA'+uuid4().hex)
  row=self.metrics()['totals']
  self.assertEqual((row.get('incoming_calls',0),row.get('incoming_talk_seconds',0)),(1,45))
try:
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IncomingReportingTests))
 raise SystemExit(0 if result.wasSuccessful() else 1)
finally:engine.dispose()

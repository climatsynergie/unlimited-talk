"""Real PG publication-order regressions, scoped synthetic imports, no provider I/O."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os,threading,unittest,json
from uuid import uuid4
from unittest.mock import patch
from app.database import make_engine
from app.identity.service import query
from app.contacts import dispatch,service,tasks
assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
assert os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine();worker_engine=make_engine()
with engine.connect() as db:
 assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'

class DueFixtureEngine:
 """Make only test IDs due inside the publisher's first transaction.

 Other processes see their original future lease until the tested dispatcher
 commits. This isolates the test from the running background dispatcher.
 """
 def __init__(self,identifiers,prime=True):self.identifiers=identifiers;self.prime=prime
 @contextmanager
 def begin(self):
  with engine.begin() as db:
   if self.prime:
    self.prime=False
    query(db,'UPDATE staging.contact_imports SET next_publish_at=now() WHERE id=ANY(CAST(:ids AS uuid[]))',ids=[str(i) for i in self.identifiers])
   yield db

class ImportDispatchRaceTests(unittest.TestCase):
 def setUp(self):
  self.identifiers=[];self.actor=uuid4()
  with engine.begin() as db:
   query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'QA dispatch race','agent','unused')",id=self.actor,email=str(self.actor)+'@example.invalid')
  original=dispatch.query
  def scoped_query(db,statement,**values):
   if 'SELECT id FROM staging.contact_imports' in statement:
    statement=statement.replace('ORDER BY next_publish_at', 'AND id=ANY(CAST(:qa_ids AS uuid[])) ORDER BY next_publish_at')
    values['qa_ids']=[str(i) for i in self.identifiers]
   return original(db,statement,**values)
  self.scope=patch.object(dispatch,'query',scoped_query);self.scope.start()
 def tearDown(self):
  self.scope.stop()
  with engine.begin() as db:
   # Failed-before fixtures stay outside background dispatch; no unfinished
   # synthetic job is left due after the test process exits.
   query(db,"UPDATE staging.contact_imports SET next_publish_at=now()+interval '1 day' WHERE id=ANY(CAST(:ids AS uuid[])) AND status IN ('queued','running')",ids=[str(i) for i in self.identifiers])
   query(db,'UPDATE staging.identity_users SET is_active=false WHERE id=:id',id=self.actor)
 def prepare(self):
  identifier=uuid4();self.identifiers.append(identifier)
  with engine.begin() as db:
   for _ in range(100):
    phone='+1613555'+f'{uuid4().int%10000:04d}'
    if not query(db,'SELECT 1 FROM staging.contacts WHERE phone=:phone',phone=phone).first():break
   else:raise AssertionError('Synthetic phones exhausted')
   query(db,"""INSERT INTO staging.contact_imports(id,created_by,filename,encoding,status,source_key,total,confirmed_at,next_publish_at)
    VALUES (:id,:actor,'qa-dispatch-race.csv','utf-8-sig','queued',:source,1,now(),now()+interval '1 day')""",id=identifier,actor=self.actor,source='qa-dispatch-race/'+str(identifier))
   query(db,"""INSERT INTO staging.contact_import_rows(import_id,row_number,profile,duplicate_in_file)
    VALUES (:id,1,CAST(:profile AS jsonb),false)""",id=identifier,profile=json.dumps(dict(phone=phone)))
  return identifier
 def row(self,identifier):
  with engine.connect() as db:return dict(query(db,"SELECT status,processed,next_publish_at,clock_timestamp() AS clock FROM staging.contact_imports WHERE id=:id",id=identifier).mappings().one())
 def history(self,identifier):
  with engine.connect() as db:return query(db,'SELECT count(*) FROM staging.contact_history WHERE import_id=:id',id=identifier).scalar_one()
 def test_broker_delivery_can_process_before_publish_returns(self):
  identifier=self.prepare();results=[]
  def publish(value):results.append(service.apply_chunk(worker_engine,value))
  self.assertEqual(dispatch.dispatch_once(DueFixtureEngine(self.identifiers),publish),1)
  self.assertEqual(results,[True],'The broker delivery was discarded while the publisher still held the job lock.')
  self.assertEqual((self.row(identifier)['status'],self.row(identifier)['processed']),('completed',1))
 def test_actual_worker_task_does_not_return_success_without_work(self):
  identifier=self.prepare();completed=[]
  def publish(value):
   with patch.object(tasks,'_engine',worker_engine):tasks.apply.run(value)
   completed.append(self.row(identifier)['processed'])
  dispatch.dispatch_once(DueFixtureEngine(self.identifiers),publish)
  self.assertEqual(completed,[1],'Task returned normally (would ACK) but skipped the locked queued job.')
 def test_duplicate_delivery_applies_each_row_once(self):
  identifier=self.prepare();results=[]
  def publish(value):
   results.extend([service.apply_chunk(worker_engine,value),service.apply_chunk(worker_engine,value)])
  dispatch.dispatch_once(DueFixtureEngine(self.identifiers),publish)
  self.assertEqual(results,[True,False]);self.assertEqual(self.history(identifier),1)
 def test_failed_publication_preserves_a_bounded_retry_and_recovers(self):
  identifier=self.prepare();original=self.row(identifier)
  def offline(value):raise ConnectionError('Synthetic broker outage')
  with self.assertRaises(ConnectionError):dispatch.dispatch_once(DueFixtureEngine(self.identifiers),offline)
  row=self.row(identifier)
  self.assertEqual((row['status'],row['processed']),('queued',0))
  # Original implementation rolls back the test-only due change; the new
  # committed claim must instead retain a bounded publication lease.
  self.assertTrue(row['next_publish_at']==original['next_publish_at'] or row['next_publish_at']<=row['clock']+timedelta(seconds=31))
  dispatch.dispatch_once(DueFixtureEngine(self.identifiers),lambda value:service.apply_chunk(worker_engine,value))
  self.assertEqual(self.row(identifier)['status'],'completed');self.assertEqual(self.history(identifier),1)
 def test_competing_dispatcher_does_not_publish_a_claimed_lease(self):
  identifier=self.prepare();entered=threading.Event();release=threading.Event();published=[]
  def publish(value):
   published.append(value);entered.set()
   if not release.wait(5):raise AssertionError('Second dispatcher did not complete')
  with ThreadPoolExecutor(max_workers=1) as pool:
   first=pool.submit(dispatch.dispatch_once,DueFixtureEngine(self.identifiers),publish)
   try:
    self.assertTrue(entered.wait(5))
    self.assertEqual(dispatch.dispatch_once(DueFixtureEngine(self.identifiers,prime=False),lambda value:published.append(value)),0)
   finally:release.set()
   self.assertEqual(first.result(timeout=10),1)
  self.assertEqual(published,[str(identifier)])
 def test_partial_batch_failure_keeps_completed_work_and_pending_retry(self):
  identifiers=[self.prepare(),self.prepare()];published=[]
  def publish(value):
   published.append(value)
   if len(published)==2:raise ConnectionError('Synthetic second publication failure')
   service.apply_chunk(worker_engine,value)
  with self.assertRaises(ConnectionError):dispatch.dispatch_once(DueFixtureEngine(self.identifiers),publish)
  first,second=published
  self.assertEqual(self.row(first)['status'],'completed')
  pending=self.row(second)
  self.assertEqual((pending['status'],pending['processed']),('queued',0))
  self.assertLessEqual(pending['next_publish_at'],pending['clock']+timedelta(seconds=31))
  dispatch.dispatch_once(DueFixtureEngine(self.identifiers),lambda value:service.apply_chunk(worker_engine,value))
  self.assertTrue(all(self.row(i)['status']=='completed' and self.history(i)==1 for i in identifiers))
try:
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ImportDispatchRaceTests))
 raise SystemExit(0 if result.wasSuccessful() else 1)
finally:engine.dispose();worker_engine.dispose()

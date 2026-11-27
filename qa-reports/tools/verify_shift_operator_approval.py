"""Prepare a pinned API approval for root-maintained VM operations, without applying.

Only the exact current-main API86230a2 is added. Existing provenance, readiness,
manual calling, campaign scope, quota, media drain and rollback checks remain.
"""
from pathlib import Path
import ast,difflib,hashlib,importlib.util,json,types,unittest
root=Path(__file__).resolve().parents[2];out=root/'qa-reports/evidence';out.mkdir(parents=True,exist_ok=True)
revision='86230a2fa1a3a6b2af5b8d1e60144fbb9191c5c2';worker='276673bb997924b82c7e8ad89871113e15d8a212'
sources=[('vmhunter_worker_release.py','/usr/local/sbin/unlimited-talk-vmhunter-worker-release',
 'revision not in {API_BASE,POLICY_V4_API,worker_revision}',
 'revision not in {API_BASE,POLICY_V4_API,worker_revision,'+repr(revision)+'}'),
 ('configure_vmhunter_campaigns.py','/usr/local/sbin/unlimited-talk-vmhunter-campaigns',
 "api_revision in {'35b4ba8f076b9ead2712aed239656a8423eb09ff','36a451a4e974dc0a8ff80bbe5540806f57fa3c6f',revision}",
 "api_revision in {'35b4ba8f076b9ead2712aed239656a8423eb09ff','36a451a4e974dc0a8ff80bbe5540806f57fa3c6f',revision,"+repr(revision)+'}')]
records=[];modules=[]
for filename,destination,needle,replacement in sources:
 source=(root/'scripts'/filename).read_text();assert source.count(needle)==1
 candidate=source.replace(needle,replacement)
 module=types.ModuleType('approved_'+filename.removesuffix('.py'));module.__file__=str(root/'scripts'/filename)
 exec(compile(candidate,module.__file__,'exec'),module.__dict__);modules.append(module)
 records.append(dict(destination=destination,before_sha256=hashlib.sha256(source.encode()).hexdigest(),after_sha256=hashlib.sha256(candidate.encode()).hexdigest(),source=candidate))
 (out/('shift-approved-'+filename)).write_text(candidate)
 (out/('shift-approved-'+filename+'.patch')).write_text(''.join(difflib.unified_diff(source.splitlines(True),candidate.splitlines(True),fromfile=filename,tofile=filename+' (API86230a2 approval)')))

def load(name,filename):
 spec=importlib.util.spec_from_file_location(name,root/'tests/host'/filename)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
wt=load('worker_host_tests','test_vmhunter_worker_release.py');original=wt.module;wt.module=modules[0]
ct=load('campaign_host_tests','test_campaign_release_request.py');ct.configuration=modules[1]
class ExactApprovalTests(unittest.TestCase):
 def health(self):return wt.WorkerReleaseTests().health(revision)
 def test_original_refuses_and_reviewed_candidate_accepts_only_the_pinned_api(self):
  with self.assertRaises(ValueError):original.compatible_api_revision('git-'+revision,self.health(),worker)
  self.assertEqual(modules[0].compatible_api_revision('git-'+revision,self.health(),worker),revision)
  with self.assertRaises(ValueError):modules[0].compatible_api_revision('git-'+'f'*40,self.health()|{'revision':'f'*40},worker)
 def test_new_approval_still_requires_matching_healthy_manual_schema_twelve(self):
  for change in ({'calling_enabled':False},{'status':'unready'},{'environment':'production'},{'migration':'0011_long_recordings'},{'communications':'disabled'},{'revision':'f'*40}):
   with self.subTest(change=change),self.assertRaises(ValueError):modules[0].compatible_api_revision('git-'+revision,self.health()|change,worker)
 def test_campaign_assertion_adds_only_reviewed_api_and_preserves_worker_binding(self):
  def approved(source,api):
   assertions=[n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Assert) and isinstance(n.test,ast.Compare) and isinstance(n.test.left,ast.Name) and n.test.left.id=='api_revision']
   self.assertEqual(len(assertions),1)
   return eval(compile(ast.Expression(assertions[0].test),'<scoped approval>','eval'),{'api_revision':api,'revision':worker})
  old=(root/'scripts/configure_vmhunter_campaigns.py').read_text()
  self.assertFalse(approved(old,revision));self.assertTrue(approved(records[1]['source'],revision))
  self.assertFalse(approved(records[1]['source'],'f'*40))
suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(wt.WorkerReleaseTests),unittest.defaultTestLoader.loadTestsFromTestCase(ct.CampaignConfigurationTests),unittest.defaultTestLoader.loadTestsFromTestCase(ExactApprovalTests)])
result=unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():raise SystemExit(1)
(out/'shift-operator-compatibility-approved-86230a2f.json').write_text(json.dumps(dict(api_revision=revision,files=records,applied=False),indent=2)+'\n')
print(json.dumps(dict(tests=result.testsRun,approved_api=revision,root_operators_applied=False,files=[{k:v for k,v in r.items() if k!='source'} for r in records])))

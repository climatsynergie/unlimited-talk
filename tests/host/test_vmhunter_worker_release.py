"""An independent quota update must never replace API/call configuration."""
import importlib.util,json
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('vmworker_release',Path(__file__).resolve().parents[2]/'scripts/vmhunter_worker_release.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class WorkerReleaseTests(unittest.TestCase):
    def health(self,revision):return dict(revision=revision,status='ready',environment='staging',migration='0012_incoming_runtime',communications='manual',calling_enabled=True)
    def test_known_compatible_apis_and_same_source_api_are_accepted(self):
        for revision in (module.API_BASE,module.POLICY_V4_API,'a'*40):
            self.assertEqual(module.compatible_api_revision('git-'+revision,self.health(revision),'a'*40),revision)
    def test_unknown_or_disabled_api_cannot_receive_an_independent_update(self):
        revision=module.POLICY_V4_API
        for change in ({'calling_enabled':False},{'calling_enabled':1},{'status':'unready'},
                {'environment':'production'},{'migration':'0011_long_recordings'},
                {'communications':'webhooks_only'},{'revision':'f'*40}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                module.compatible_api_revision('git-'+revision,self.health(revision) | change,'a'*40)
        with self.assertRaises(ValueError):module.compatible_api_revision('git-'+'f'*40,self.health('f'*40),'a'*40)
    def test_free_allowance_changes_only_worker_image_and_nonsecret_quota_config(self):
        previous={'services':{'vmhunter':{'image':'old@sha256:test','environment':{'COMMUNICATIONS_MODE':'manual'},'secrets':['five-existing-secrets'],'read_only':True,'user':'10001:10001','networks':['private']}},'networks':{'private':{'external':True}}}
        before=json.loads(json.dumps(previous))
        value=module.configured_worker(previous,'new@sha256:test',5000)
        self.assertEqual(previous,before)
        self.assertEqual(value['services']['vmhunter']['environment'],dict(COMMUNICATIONS_MODE='manual',VMHUNTER_QUOTA_SOURCE='provider',VMHUNTER_MONTHLY_ALLOWANCE='5000'))
        value['services']['vmhunter']['image']=before['services']['vmhunter']['image']
        value['services']['vmhunter']['environment']=before['services']['vmhunter']['environment']
        self.assertEqual(value,before)
        for invalid in (True,5000.0,100000,'5000'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):module.configured_worker(previous,'new',invalid)
        with self.assertRaises(ValueError):module.configured_worker({'services':{'api':{},'vmhunter':{}}},'new',5000)

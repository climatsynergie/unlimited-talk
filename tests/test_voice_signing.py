"""Signing provisioner: no Rule writes, private secrets and lost-response safety."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

scripts=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('voice_signing',scripts/'twilio_voice_signing.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class SigningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'journal';self.key=self.path.with_name('key')
        self.config=dict(account_sid='AC'+'a'*32,api_key_sid='SK'+'b'*32,api_key_secret='c'*32,
            phone_number_sid='PN'+'d'*32,caller_number='+14165550100',approved_destination='+14165550101',public_origin='https://staging.unlimitedtalkapp.com')
        self.inventory={name:{} for name in module.RESOURCES}
        self.old_rule='webhooks_rule_'+'z'*26
        self.inventory['Rules'][self.old_rule]=dict(id=self.old_rule,friendlyName='Legacy',matchType='DEFAULT',settings=[])
        self.calls=[];self.lost=None
        self.provider=module.Provider(self.config,self.send)

    def tearDown(self):self.tmp.cleanup()

    def send(self,request):
        self.calls.append(request)
        path=request.full_url.split('/v1/Webhooks')[1]
        if request.method=='GET':
            parts=path.strip('/').split('/')
            if len(parts)==1:
                name=parts[0];field=module.RESOURCES[name][0]
                return {field:list(copy.deepcopy(self.inventory[name]).values()),'meta':{'nextToken':None}}
            return copy.deepcopy(self.inventory[parts[0]][parts[1]])
        self.assertEqual(request.method,'POST')
        body=json.loads(request.data)
        if path=='/SharedKeys':
            key=dict(id='webhooks_sharedkey_'+'e'*26,secret='f'*32,friendlyName=module.NAME)
            self.inventory['SharedKeys'][key['id']]={k:v for k,v in key.items() if k!='secret'}
            result=key
        elif path=='/Settings':
            result={'id':'webhooks_setting_'+'g'*26,**body}
            self.inventory['Settings'][result['id']]=result
        else:raise AssertionError('Rule writes forbidden')
        if self.lost==path:raise TimeoutError('synthetic lost response')
        return copy.deepcopy(result)

    def run_action(self,action):return module.run(action,self.config,self.path,self.key,self.provider)

    def posts(self):return [r for r in self.calls if r.method=='POST']

    def test_preparation_is_read_only_and_apply_creates_only_key_and_setting_once(self):
        before=copy.deepcopy(self.inventory['Rules'])
        self.assertEqual(self.run_action('prepare')['state'],'prepared');self.assertFalse(self.posts())
        report=self.run_action('apply');self.assertEqual(report['state'],'verified')
        self.assertEqual(self.key.stat().st_mode&0o777,0o600)
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertEqual(len(self.posts()),2)
        self.assertEqual(self.run_action('check')['state'],'verified')
        self.run_action('apply');self.assertEqual(len(self.posts()),2)
        self.assertEqual(self.inventory['Rules'],before)
        self.assertFalse(report['rule_applied']);self.assertFalse(report['calling_enabled'])
        self.assertNotIn('f'*32,json.dumps(report));self.assertNotIn('c'*32,json.dumps(report))

    def test_lost_key_response_never_causes_another_key_creation(self):
        self.run_action('prepare');self.lost='/SharedKeys'
        with self.assertRaises(TimeoutError):self.run_action('apply')
        self.assertFalse(self.key.exists())
        for action in ['check','apply']:
            with self.assertRaises(module.PreflightError):self.run_action(action)
        self.assertEqual(len(self.posts()),1)

    def test_lost_setting_response_reconciles_without_new_post(self):
        self.run_action('prepare');self.lost='/Settings'
        with self.assertRaises(TimeoutError):self.run_action('apply')
        self.assertTrue(self.key.exists());self.lost=None
        self.assertEqual(self.run_action('check')['state'],'verified')
        self.assertEqual(len(self.posts()),2)

    def test_existing_rule_drift_blocks_creation_and_mismatched_profile_blocks_resume(self):
        self.run_action('prepare');self.inventory['Rules'][self.old_rule]['friendlyName']='Changed'
        with self.assertRaises(module.PreflightError):self.run_action('apply')
        self.assertFalse(self.posts())
        self.config['approved_destination']='+14165550102'
        with self.assertRaises(module.PreflightError):self.run_action('apply')

    def test_method_allowlist_refuses_rules_deletes_and_unsafe_key_settings(self):
        for method,path,body in [('POST','/Rules',{}),('DELETE','/SharedKeys/x',None),
                                 ('POST','/Settings',{'signature':{'type':'ACCOUNT_AUTH_TOKEN'}}),
                                 ('POST','/SharedKeys',{'friendlyName':'other'}),
                                 ('GET','/SharedKeys?PageSize=1',None),('GET','https://untrusted.example',None)]:
            with self.assertRaises(module.PreflightError):self.provider.request(method,path,body)
        self.assertEqual(self.calls,[])

    def test_duplicate_resource_name_cannot_be_adopted_automatically(self):
        self.inventory['SharedKeys']['webhooks_sharedkey_'+'e'*26]=dict(id='webhooks_sharedkey_'+'e'*26,friendlyName=module.NAME)
        with self.assertRaises(module.PreflightError):self.run_action('prepare')
        self.assertFalse(self.path.exists())

    def test_assembled_profile_is_bound_to_verified_key_application_and_original_target(self):
        self.run_action('prepare');self.run_action('apply')
        application=dict(version=1,binding=module.binding(self.config),state='verified',before_applications={},before_numbers={},application_sid='AP'+'1'*32)
        value=module.assemble(self.config,module.read_private(self.path),module.read_private(self.key),application)
        self.assertEqual(value['approved_destination'],self.config['approved_destination'])
        self.assertEqual(value['mode'],'controlled_test')
        self.assertEqual(value['shared_key_secret'],'f'*32)
        application['state']='prepared'
        with self.assertRaises(module.PreflightError):module.assemble(self.config,module.read_private(self.path),module.read_private(self.key),application)


if __name__=='__main__':unittest.main()

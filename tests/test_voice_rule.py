import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import twilio_voice_rule as module


class VoiceRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'twilio-voice-rule.json';self.source_path=self.root/'signing.json';self.key_path=self.root/'key.json'
        self.receipt=self.root/'voice-delivery-20261031T173646557476.json'
        self.config=dict(account_sid='AC'+'a'*32,api_key_sid='SK'+'b'*32,api_key_secret='c'*32,
            phone_number_sid='PN'+'d'*32,caller_number='+14165550100',approved_destination='+14165550101',
            public_origin='https://staging.unlimitedtalkapp.com')
        self.key=dict(id='webhooks_sharedkey_'+'e'*26,secret='f'*32,friendlyName=module.signing.NAME)
        self.setting={'id':'webhooks_setting_'+'g'*26,**module.signing.setting(self.key['id'])}
        self.legacy=dict(id='webhooks_rule_'+'z'*26,friendlyName='Legacy',matchType='DEFAULT',settings=[])
        self.inv={'SharedKeys':{self.key['id']:{k:v for k,v in self.key.items() if k!='secret'}},
            'Settings':{self.setting['id']:self.setting},'Rules':{self.legacy['id']:self.legacy}}
        self.source=dict(version=1,state='verified',binding=module.signing.binding(self.config),key_id=self.key['id'],
            setting_id=self.setting['id'],before={'SharedKeys':{},'Settings':{},'Rules':module.signing.fingerprints(self.inv['Rules'])})
        for path,data in [(self.source_path,self.source),(self.key_path,self.key),
            (self.receipt,dict(url=module.signing.RULE_PREFIX+'probe',result=dict(outcome='DELIVERED',response=204)))]:
            module.save(data,path)
        os.utime(self.receipt,(1000,1000))
        self.calls=[];self.lost=False;self.status='RUNNING'
        self.provider=module.Provider(self.config,self.setting['id'],self.send)
        self.patches=[patch.object(module.signing,'JOURNAL',self.source_path),patch.object(module.signing,'KEY',self.key_path)]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def operation(self):
        return dict(id='webhooks_operation_'+'o'*26,resourceId='webhooks_rule_'+'r'*26,status=self.status)

    def send(self,request):
        self.calls.append(request)
        path=request.full_url.split('/v1/Webhooks')[1]
        if request.method=='POST':
            self.assertEqual(path,'/Rules')
            body=json.loads(request.data);self.assertEqual(body,module.signing.route_setting(self.setting['id']))
            row={'id':'webhooks_rule_'+'r'*26,**body};self.inv['Rules'][row['id']]=row
            if self.lost:raise TimeoutError('lost acceptance response')
            return dict(rule=row,operation=self.operation()),dict(operation_id=self.operation()['id'],retry_after='5')
        if path.startswith('/Operations?'):
            return dict(operations=[self.operation()],meta=dict(nextToken=None)),{}
        if path.startswith('/Operations/'):
            return self.operation(),{}
        parts=path.strip('/').split('/')
        if len(parts)==1:
            name=parts[0];field=module.signing.RESOURCES[name][0]
            return {field:copy.deepcopy(list(self.inv[name].values())),'meta':{'nextToken':None}}
        return copy.deepcopy(self.inv[parts[0]][parts[1]])

    def run_action(self,action,now=1000):
        return module.run(action,self.config,path=self.path,receipt=self.receipt,provider=self.provider,now=now)

    def posts(self):return [r for r in self.calls if r.method=='POST']

    def test_preparation_does_not_write_and_propagation_must_finish(self):
        self.assertEqual(self.run_action('prepare')['state'],'prepared');self.assertFalse(self.posts())
        self.assertEqual(self.run_action('apply')['state'],'propagating')
        self.assertEqual(self.run_action('check',1004)['state'],'propagating')
        self.assertFalse(any('/Operations/' in r.full_url for r in self.calls))
        self.status='COMPLETED'
        result=self.run_action('check',1005);self.assertEqual(result['state'],'verified')
        self.assertFalse(result['calling_enabled']);self.assertEqual(len(self.posts()),1)
        self.run_action('apply',1010);self.assertEqual(len(self.posts()),1)
        self.assertEqual(self.inv['Rules'][self.legacy['id']],self.legacy)
        module.signing.preserved(self.source,self.inv,module.read_private(self.path))
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)

    def test_lost_write_response_reconciles_rule_and_operation_without_second_post(self):
        self.run_action('prepare');self.lost=True
        with self.assertRaises(TimeoutError):self.run_action('apply')
        self.assertEqual(module.read_private(self.path)['state'],'requested')
        self.status='COMPLETED'
        self.assertEqual(self.run_action('check',1006)['state'],'verified')
        self.assertEqual(len(self.posts()),1)

    def test_missing_or_failed_probe_never_allows_rule_creation(self):
        bad=dict(url=module.signing.RULE_PREFIX+'probe',result=dict(outcome='FAILED',response=403))
        module.save(bad,self.receipt,replace=True)
        with self.assertRaises(module.PreflightError):self.run_action('prepare')
        self.assertFalse(self.posts())

    def test_stale_delivery_blocks_a_new_write(self):
        self.run_action('prepare')
        with self.assertRaises(module.PreflightError):self.run_action('apply',2000)
        self.assertFalse(self.posts())

    def test_legacy_or_owned_rule_drift_fails_closed(self):
        self.run_action('prepare');self.run_action('apply')
        self.inv['Rules'][self.legacy['id']]={**self.legacy,'friendlyName':'Changed'}
        with self.assertRaises(module.PreflightError):self.run_action('check',1005)
        self.inv['Rules'][self.legacy['id']]=self.legacy
        rid='webhooks_rule_'+'r'*26
        self.inv['Rules'][rid]['prefix']='https://staging.unlimitedtalkapp.com/'
        with self.assertRaises(module.PreflightError):self.run_action('check',1005)

    def test_foreign_operation_cannot_prove_propagation(self):
        self.run_action('prepare');self.run_action('apply')
        with patch.object(self,'operation',return_value=dict(id='webhooks_operation_'+'o'*26,
            resourceId=self.legacy['id'],status='COMPLETED')):
            with self.assertRaises(module.PreflightError):self.run_action('check',1005)

    def test_transport_never_accepts_default_patch_delete_or_untrusted_urls(self):
        for method,path,body in [('POST','/Rules',dict(matchType='DEFAULT',settings=[])),
            ('PATCH','/Rules/webhooks_rule_'+'r'*26,{}),('DELETE','/Rules/webhooks_rule_'+'r'*26,None),
            ('GET','https://untrusted.invalid',None),('GET','/Operations?resourceId=anything',None)]:
            with self.assertRaises(module.PreflightError):self.provider.request(method,path,body)
        self.assertFalse(self.calls)

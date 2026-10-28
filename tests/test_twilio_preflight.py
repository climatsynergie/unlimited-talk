"""Read-only provider preparation with synthetic credentials and no network."""
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

path=Path(__file__).resolve().parents[1]/'scripts/staging_twilio_preflight.py'
spec=importlib.util.spec_from_file_location('twilio_preflight',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class TwilioFixture:
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'twilio.json'
        self.config=dict(version=1,mode='read_only',region='us1',account_sid='AC'+'a'*32,api_key_sid='SK'+'b'*32,api_key_secret='c'*32,phone_number_sid='PN'+'d'*32,caller_number='+14165550100')
        self.number=dict(account_sid=self.config['account_sid'],sid=self.config['phone_number_sid'],phone_number=self.config['caller_number'],capabilities=dict(voice=True,sms=True),voice_url='https://private.invalid/inbound',trunk_sid=None)

    def tearDown(self):self.tmp.cleanup()


class TwilioPreflightTests(TwilioFixture,unittest.TestCase):
    def test_only_selected_number_get_is_constructed_and_no_secret_is_reported(self):
        calls=[]
        def send(request):calls.append(request);return self.number
        result=module.check(self.config,send)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0].get_method(),'GET')
        self.assertEqual(calls[0].full_url,'https://api.twilio.com/2010-04-01/Accounts/'+self.config['account_sid']+'/IncomingPhoneNumbers/'+self.config['phone_number_sid']+'.json')
        expected='Basic '+base64.b64encode((self.config['api_key_sid']+':'+self.config['api_key_secret']).encode()).decode()
        self.assertEqual(calls[0].get_header('Authorization'),expected)
        self.assertTrue(result['voice_capability']);self.assertTrue(result['existing_inbound_route'])
        self.assertFalse(result['configuration_changed']);self.assertFalse(result['live_call_verified'])
        for secret in [self.config['api_key_secret'],self.config['api_key_sid'],self.config['caller_number'],'private.invalid']:
            self.assertNotIn(secret,json.dumps(result))

    def test_invalid_modes_regions_and_injected_identifiers_cannot_send(self):
        for key,value in [('mode','live'),('region','ie1'),('account_sid','AC../Calls'),('phone_number_sid','PN'+'d'*32+'/Calls'),('api_key_sid','x'),('api_key_secret','short'),('caller_number','+1\nHeader: value')]:
            with self.subTest(key=key),patch.object(module,'transport') as send,self.assertRaises(module.PreflightError):
                module.check({**self.config,key:value},send)
            send.assert_not_called()

    def test_response_identity_and_capability_types_are_checked(self):
        for change in [dict(account_sid='AC'+'e'*32),dict(sid='PN'+'f'*32),dict(phone_number='+14165550101'),dict(capabilities=None)]:
            with self.subTest(change=change),self.assertRaises(module.PreflightError):
                module.check(self.config,lambda request:{**self.number,**change})
        result=module.check(self.config,lambda request:{**self.number,'capabilities':{'voice':'true'}})
        self.assertFalse(result['voice_capability'])

    def test_private_store_refuses_overwrite_and_symlinks(self):
        module.store(self.config,self.path)
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertEqual(module.load(self.path),self.config)
        with self.assertRaises(FileExistsError):module.store({**self.config,'api_key_secret':'z'*32},self.path)
        self.assertEqual(module.load(self.path),self.config)
        link=self.path.parent/'link.json';link.symlink_to(self.path)
        with self.assertRaises(FileExistsError):module.store(self.config,link)
        with self.assertRaises(OSError):module.load(link)

    def test_permissions_links_size_and_json_are_bounded(self):
        module.store(self.config,self.path);self.path.chmod(0o640)
        with self.assertRaises(module.PreflightError):module.load(self.path)
        self.path.chmod(0o600);link=self.path.parent/'hardlink';os.link(self.path,link)
        with self.assertRaises(module.PreflightError):module.load(self.path)
        link.unlink();self.path.write_text('x'*8193)
        with self.assertRaises(module.PreflightError):module.load(self.path)
        self.path.write_text('not-json')
        with self.assertRaises(module.PreflightError):module.load(self.path)

    def test_http_errors_and_unexpected_failures_never_echo_credentials(self):
        def denied(request):raise urllib.error.HTTPError(request.full_url,401,self.config['api_key_secret'],{},None)
        with self.assertRaises(module.PreflightError) as error:module.check(self.config,denied)
        self.assertNotIn(self.config['api_key_secret'],str(error.exception))
        stderr=io.StringIO()
        with patch.object(module.os,'geteuid',return_value=0),patch.object(module,'load',return_value=self.config),patch.object(module,'check',side_effect=RuntimeError(self.config['api_key_secret'])),contextlib.redirect_stderr(stderr):
            self.assertEqual(module.main(['check']),1)
        self.assertNotIn(self.config['api_key_secret'],stderr.getvalue())

    def test_redirects_cannot_forward_the_authorization_header(self):
        with self.assertRaises(module.PreflightError):
            module.NoRedirect().redirect_request(None,None,302,'Found',{},'https://other.invalid/')

    def test_mismatched_secret_confirmation_does_not_create_a_file(self):
        values=iter([self.config['account_sid'],self.config['api_key_sid'],self.config['api_key_secret'],'wrong'])
        with self.assertRaises(module.PreflightError):module.collect(lambda label:next(values))
        self.assertFalse(self.path.exists())

    def test_unprivileged_cli_does_not_prompt_for_credentials(self):
        with patch.object(module.os,'geteuid',return_value=10001),patch.object(module,'collect') as prompt,contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(module.main(['store']),1)
            prompt.assert_not_called()


class SipProfileTests(TwilioFixture,unittest.TestCase):
    def plan(self):
        return dict(version=1,mode='credentials_only',account_sid=self.config['account_sid'],phone_number_sid=self.config['phone_number_sid'],caller_number=self.config['caller_number'],trunk_sid='TK'+'e'*32,termination_domain='unlimitedtalk.pstn.twilio.com',require_secure_trunk=True,recording_source='asterisk')

    def profile(self):return {**self.plan(),'sip_username':'ut-pbx','sip_password':'ExampleOnlyCredential1234'}

    def test_sip_profile_is_private_bound_and_does_not_report_password(self):
        module.store_sip(self.profile(),self.config,self.path)
        profile=module.read_private(self.path)
        self.assertEqual(profile,self.profile())
        report=module.sip_report(profile,self.config)
        self.assertFalse(report['live_call_verified']);self.assertFalse(report['engine_configuration_verified']);self.assertFalse(report['sip_authentication_verified'])
        for value in [profile['sip_password'],profile['sip_username'],profile['caller_number'],profile['account_sid']]:self.assertNotIn(value,json.dumps(report))
        with self.assertRaises(FileExistsError):module.store_sip(self.profile(),self.config,self.path)

    def test_unsafe_sip_targets_and_live_destinations_are_rejected(self):
        for change in [dict(termination_domain='attacker.invalid'),dict(termination_domain='unlimitedtalk.pstn.twilio.com/Calls'),dict(require_secure_trunk=False),dict(mode='live'),dict(approved_destinations=['+14165550101']),dict(account_sid='AC'+'f'*32),dict(phone_number_sid='PN'+'f'*32),dict(caller_number='+14165550101')]:
            with self.subTest(change=change),self.assertRaises(module.PreflightError):module.validate_sip_plan({**self.plan(),**change},self.config)

    def test_sip_credentials_validate_before_persisting(self):
        for change in [dict(sip_username='bad\nuser'),dict(sip_password='weak'),dict(sip_password='x'*24),dict(sip_password='Example Secret1234')]:
            with self.subTest(change=change),self.assertRaises(module.PreflightError):module.store_sip({**self.profile(),**change},self.config,self.path)
            self.assertFalse(self.path.exists())
        values=iter(['ut-pbx','ExampleOnlyCredential1234','mismatch'])
        with self.assertRaises(module.PreflightError):module.collect_sip(self.plan(),self.config,lambda label:next(values))
        self.assertFalse(self.path.exists())

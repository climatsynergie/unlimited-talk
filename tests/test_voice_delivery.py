import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

scripts=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('voice_delivery',scripts/'twilio_voice_delivery_test.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class Response(io.BytesIO):
    status=200


class VoiceDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(account_sid='AC'+'a'*32,api_key_sid='SK'+'b'*32,api_key_secret='c'*32,
            phone_number_sid='PN'+'d'*32,caller_number='+14165550100',approved_destination='+14165550101',
            public_origin='https://staging.unlimitedtalkapp.com')
        self.key=dict(id='webhooks_sharedkey_'+'e'*26,secret='f'*32,friendlyName=module.signing.NAME)
        self.journal=dict(state='verified',binding=module.signing.binding(self.config),
            key_id=self.key['id'],setting_id='webhooks_setting_'+'g'*26)
        self.target=self.config['public_origin']+'/api/telephony/twilio/probe'

    def invoke(self, result):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('os.geteuid',return_value=0))
            stack.enter_context(patch.object(module.urllib.request,'urlopen',return_value=Response(json.dumps(
                dict(status='ready',communications='webhooks_only',calling_enabled=False)).encode())))
            stack.enter_context(patch.object(module.voice,'load_base',return_value={}))
            stack.enter_context(patch.object(module.voice,'validate_plan',return_value={}))
            stack.enter_context(patch.object(module.voice,'validate_credentials',return_value=self.config))
            stack.enter_context(patch.object(module,'read_private',side_effect=lambda p:
                self.journal if p==module.signing.JOURNAL else self.key if p==module.signing.KEY else {}))
            provider=stack.enter_context(patch.object(module.signing,'Provider')).return_value
            provider.request.return_value={'id':self.journal['setting_id'],**module.signing.setting(self.key['id'])}
            opener=stack.enter_context(patch.object(module.urllib.request,'build_opener')).return_value
            opener.open.return_value=Response(json.dumps(result).encode())
            saved=stack.enter_context(patch.object(module,'write_private'))
            output=io.StringIO();stack.enter_context(contextlib.redirect_stdout(output))
            if result.get('result',{}).get('outcome')=='DELIVERED' and module.delivery_code(result['result']['response'])==204:
                module.run()
            else:
                with self.assertRaises(module.PreflightError):module.run()
            request=opener.open.call_args.args[0]
            self.assertEqual(request.method,'POST')
            self.assertEqual(request.full_url,'https://webhooks.twilio.com/v1/Webhooks/Tests')
            self.assertEqual(json.loads(request.data),dict(url=self.target,settingId=self.journal['setting_id'],method='POST'))
            self.assertEqual(saved.call_count,1)
            self.assertNotIn(self.config['api_key_secret'],output.getvalue())
            self.assertNotIn(self.key['secret'],output.getvalue())
            return json.loads(output.getvalue())

    def test_only_a_delivered_204_proves_signature_acceptance(self):
        r=self.invoke(dict(url=self.target,result=dict(outcome='DELIVERED',response=204)))
        self.assertTrue(r['delivery_verified'])
        self.assertFalse(r['calling_enabled'])

    def test_api_200_does_not_hide_failed_delivery_or_a_rejected_signature(self):
        for outcome,code in [('FAILED',403),('FAILED',401),('DELIVERED',200)]:
            r=self.invoke(dict(url=self.target,result=dict(outcome=outcome,response=code)))
            self.assertFalse(r['delivery_verified'])

    def test_response_status_is_interpreted_conservatively(self):
        self.assertEqual(module.delivery_code(dict(statusCode=204)),204)
        self.assertIsNone(module.delivery_code(True))
        self.assertIsNone(module.delivery_code(dict(payload='204')))

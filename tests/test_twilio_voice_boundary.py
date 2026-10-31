"""Provider security tests using synthetic data; never originate a real call."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import UUID
from xml.etree import ElementTree

import jwt
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator

from app.telephony.twilio_voice import (
    ControlledVoiceProfile, MAX_TEST_CALL_SECONDS, TOKEN_TTL_SECONDS,
    VoiceConfigurationError, VoiceWebhookError, authenticate_webhook,
    browser_token, client_identity, controlled_call_twiml, webhook_url, authenticate_probe,
)


class VoiceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.profile = ControlledVoiceProfile(
            'AC'+'a'*32, 'SK'+'b'*32, 'c'*32, 'AP'+'d'*32,
            'webhooks_sharedkey_'+'e'*26, 'f'*32,
            'https://voice.example.com', '+14165550100', '+14165550101')
        self.agent = UUID('11111111-1111-4111-8111-111111111111')
        self.intent = UUID('22222222-2222-4222-8222-222222222222')
        self.settings = 'key='+self.profile.shared_key_id+',algorithm=HMAC_SHA1'
        self.fields = [('AccountSid', self.profile.account_sid), ('CallSid', 'CA'+'1'*32)]

    def signed(self, fields=None, kind='status', intent=None):
        fields = self.fields if fields is None else fields
        intent = self.intent if intent is None else intent
        body = urlencode(fields).encode()
        signature = RequestValidator(self.profile.shared_key_secret).compute_signature(
            webhook_url(self.profile, kind, intent), FormData(fields))
        return body, signature

    def verify(self, body, signature, **overrides):
        args = dict(profile=self.profile, kind='status', intent_id=self.intent,
                    body=body, content_type='application/x-www-form-urlencoded; charset=utf-8',
                    signature=signature, signing_settings=self.settings)
        return authenticate_webhook(**(args | overrides))

    def test_browser_token_has_bounded_lifetime_and_only_one_outgoing_app(self):
        token = browser_token(self.profile, self.agent, self.intent)
        claims = jwt.decode(token, self.profile.api_key_secret, algorithms=['HS256'],
                            issuer=self.profile.api_key_sid)
        self.assertEqual(claims['exp']-claims['nbf'], TOKEN_TTL_SECONDS)
        self.assertEqual(claims['sub'], self.profile.account_sid)
        self.assertEqual(claims['grants']['identity'], client_identity(self.agent, self.intent))
        self.assertEqual(claims['grants']['voice']['outgoing'], {'application_sid':self.profile.twiml_app_sid})
        self.assertFalse(claims['grants']['voice'].get('incoming',{}).get('allow',False))
        for value in [self.profile.api_key_secret,self.profile.shared_key_secret,
                      self.profile.caller_number,self.profile.approved_destination]:
            self.assertNotIn(value,json.dumps(claims))
        with self.assertRaises(VoiceConfigurationError):browser_token(self.profile,'untrusted',self.intent)
        self.assertNotEqual(client_identity(self.agent,self.intent),client_identity(self.agent,UUID(int=3)))

    def test_authenticates_future_fields_repeated_values_and_empty_values(self):
        fields=self.fields+[('FutureField','été & ?'),('FutureField','other'),('Empty','')]
        body,signature=self.signed(fields)
        params=self.verify(body,signature)
        self.assertEqual(params.getlist('FutureField'),['été & ?','other'])
        self.assertEqual(params['Empty'],'')
        with self.assertRaises(VoiceWebhookError):self.verify(body.replace(b'other',b'wrong'),signature)

    def test_signature_is_bound_to_configured_origin_route_and_intent(self):
        body,signature=self.signed()
        for overrides in [dict(profile=replace(self.profile,public_origin='https://other.example.com')),
                          dict(kind='recording'),dict(intent_id=UUID(int=4))]:
            with self.subTest(overrides=list(overrides)),self.assertRaises(VoiceWebhookError):
                self.verify(body,signature,**overrides)
        with self.assertRaises(VoiceConfigurationError):webhook_url(self.profile,'../../Calls',self.intent)

    def test_fixed_voice_entry_authenticates_intent_and_matching_sdk_identity(self):
        fields = self.fields + [('Intent', str(self.intent)),
                                ('From', 'client:' + client_identity(self.agent, self.intent))]
        url = webhook_url(self.profile, 'voice')
        self.assertEqual(url, self.profile.public_origin + '/api/telephony/twilio/voice')
        signature = RequestValidator(self.profile.shared_key_secret).compute_signature(url, FormData(fields))
        params = self.verify(urlencode(fields).encode(), signature, kind='voice', intent_id=None)
        self.assertEqual(params['Intent'], str(self.intent))
        for replacement in [str(UUID(int=4)), 'invalid', self.intent.hex]:
            changed = [(key, replacement if key == 'Intent' else value) for key, value in fields]
            # Even an authentic provider form must bind the exact intent to its
            # SDK identity. A valid signature alone cannot authorize a call.
            signed = RequestValidator(self.profile.shared_key_secret).compute_signature(url, FormData(changed))
            with self.assertRaises(VoiceWebhookError):
                self.verify(urlencode(changed).encode(), signed, kind='voice', intent_id=None)
        for missing in ['Intent', 'From']:
            changed = [(key, value) for key, value in fields if key != missing]
            signed = RequestValidator(self.profile.shared_key_secret).compute_signature(url, FormData(changed))
            with self.assertRaises(VoiceWebhookError):
                self.verify(urlencode(changed).encode(), signed, kind='voice', intent_id=None)
        for extra in [('Intent', str(self.intent)), ('From', 'client:' + client_identity(self.agent, self.intent))]:
            changed = fields + [extra]
            signed = RequestValidator(self.profile.shared_key_secret).compute_signature(url, FormData(changed))
            with self.assertRaises(VoiceWebhookError):
                self.verify(urlencode(changed).encode(), signed, kind='voice', intent_id=None)
        with self.assertRaises(VoiceConfigurationError):webhook_url(self.profile, 'voice', self.intent)
        with self.assertRaises(VoiceConfigurationError):webhook_url(self.profile, 'status')

    def test_parent_status_uses_fixed_url_and_requires_a_signed_owned_account_call(self):
        url = webhook_url(self.profile, 'parent-status')
        signature = RequestValidator(self.profile.shared_key_secret).compute_signature(url, FormData(self.fields))
        params = self.verify(urlencode(self.fields).encode(), signature, kind='parent-status', intent_id=None)
        self.assertEqual(params['CallSid'], self.fields[1][1])
        with self.assertRaises(VoiceWebhookError):
            self.verify(urlencode(self.fields).encode(), signature, kind='voice', intent_id=None)

    def test_probe_uses_dedicated_signed_form_or_json_hash_without_call_fields(self):
        validator=RequestValidator(self.profile.shared_key_secret)
        url=webhook_url(self.profile,'probe')
        signature=validator.compute_signature(url,{})
        authenticate_probe(self.profile,b'',None,signature,self.settings)
        authenticate_probe(self.profile,b'','application/json',signature,self.settings)
        body='{"test":true}'
        query='bodySHA256='+validator.compute_hash(body)
        signature=validator.compute_signature(url+'?'+query,{})
        authenticate_probe(self.profile,body.encode(),'application/json',signature,self.settings,query)
        for changed in [b'{"test":false}',b'bad-body']:
            with self.assertRaises(VoiceWebhookError):
                authenticate_probe(self.profile,changed,'application/json',signature,self.settings,query)
        for changed in ['arbitrary=1',query+'&extra=1']:
            with self.assertRaises(VoiceWebhookError):
                authenticate_probe(self.profile,body.encode(),'application/json',signature,self.settings,changed)

    def test_refuses_key_algorithm_and_legacy_signature_fallback(self):
        body,signature=self.signed()
        for settings in ['',None,self.settings.replace('HMAC_SHA1','HMAC_SHA256'),
                         self.settings.replace('e'*26,'g'*26),self.settings+',algorithm=HMAC_SHA1']:
            with self.subTest(settings=settings),self.assertRaises(VoiceWebhookError):
                self.verify(body,signature,signing_settings=settings)
        for signature in ['',None,'x'*1000,'A'*27+'=']:
            with self.assertRaises(VoiceWebhookError):self.verify(body,signature)

    def test_signed_foreign_accounts_ambiguous_fields_and_bad_call_ids_are_rejected(self):
        cases=[self.fields+[('AccountSid',self.profile.account_sid)],
               [('AccountSid','AC'+'9'*32),self.fields[1]],
               [self.fields[0],('CallSid','not-a-call')]]
        for fields in cases:
            body,signature=self.signed(fields)
            with self.assertRaises(VoiceWebhookError):self.verify(body,signature)

    def test_request_size_encoding_and_parameter_bounds_fail_closed(self):
        good,signature=self.signed()
        for body in [b'x'*16385,b'a=%Q1',b'a=%FF',b'a=\xff',b'missing-equals',
                     b'&'.join(b'a=x' for _ in range(129))]:
            with self.subTest(body_length=len(body)),self.assertRaises(VoiceWebhookError):
                self.verify(body,signature)
        with self.assertRaises(VoiceWebhookError):self.verify(good,signature,content_type='application/json')
        for fields in [self.fields+[('k','x'*4097)],self.fields+[('k'*129,'v')]]:
            body,signature=self.signed(fields)
            with self.assertRaises(VoiceWebhookError):self.verify(body,signature)

    def test_controlled_twiml_has_fixed_target_timeouts_and_recording_callbacks(self):
        xml=ElementTree.fromstring(controlled_call_twiml(self.profile,self.intent))
        dial=xml.find('Dial');number=dial.find('Number')
        self.assertEqual(number.text,self.profile.approved_destination)
        self.assertEqual(dial.attrib['callerId'],self.profile.caller_number)
        self.assertEqual(int(dial.attrib['timeLimit']),MAX_TEST_CALL_SECONDS)
        self.assertEqual(dial.attrib['record'],'record-from-answer-dual')
        self.assertEqual(dial.attrib['recordingStatusCallback'],webhook_url(self.profile,'recording',self.intent))
        self.assertEqual(number.attrib['statusCallback'],webhook_url(self.profile,'status',self.intent))
        self.assertIsNotNone(xml.find('Hangup'))
        with patch('socket.create_connection',side_effect=AssertionError('Network forbidden')):
            browser_token(self.profile,self.agent,self.intent)
            controlled_call_twiml(self.profile,self.intent)
            body,signature=self.signed();self.verify(body,signature)

    def test_invalid_profiles_and_repr_do_not_disclose_secrets_or_numbers(self):
        for changes in [dict(account_sid='AC../Calls'),dict(api_key_secret='short'),
                        dict(shared_key_id='wrong'),dict(shared_key_secret='x'*32+'\n'),
                        dict(public_origin='https://127.0.0.1'),dict(public_origin='http://voice.example.com'),
                        dict(public_origin='https://voice.example.com/path'),dict(public_origin='https://u:p@voice.example.com'),
                        dict(public_origin='https://voice.example.com:443'),dict(public_origin='https://bad..example.com'),
                        dict(approved_destination=self.profile.caller_number),dict(approved_destination='+1\nInjected')]:
            with self.subTest(fields=list(changes)),self.assertRaises(VoiceConfigurationError):replace(self.profile,**changes)
        for value in [self.profile.api_key_secret,self.profile.shared_key_secret,
                      self.profile.approved_destination,self.profile.caller_number]:
            self.assertNotIn(value,repr(self.profile))


if __name__=='__main__':unittest.main()

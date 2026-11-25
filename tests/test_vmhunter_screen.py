"""Pre-bridge contracts, safe decisions and real local admission HTTP tests."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from starlette.datastructures import FormData
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from fastapi import HTTPException
from twilio.request_validator import RequestValidator

from app.telephony import vmhunter as vm, vmhunter_screen as screen
from app.telephony import vmhunter_observer as observer
from app.telephony.twilio_voice import (
    ControlledVoiceProfile, VoiceConfigurationError, VoiceWebhookError,
    authenticate_webhook, controlled_call_twiml, webhook_url,
)
from test_vmhunter import PROFILE, policy


def screening_policy(**changes):
    return policy(version=2, mode='screen', screening_approved=False, **changes)


class ScreenContractTests(unittest.TestCase):
    def test_campaign_scope_requires_separate_explicit_approval_and_membership(self):
        value=screening_policy() | dict(version=3,scope='campaign',enabled=True,
            audio_approved=True,screening_approved=True)
        approved=vm.Pilot.parse(value)
        self.assertEqual(approved.scope,'campaign')
        for _ in range(20):
            row=dict(actor_id=uuid4(),contact_id=uuid4(),campaign_id=vm.PILOT_CAMPAIGN,
                destination='+14165550101',dialer_generation=1,state='authorized')
            self.assertFalse(approved.includes(row))
            self.assertTrue(approved.includes(row,campaign_member=True))
            for changes in (dict(campaign_id=uuid4()),dict(contact_id=None),
                    dict(dialer_generation=None),dict(state='finished'),dict(destination='invalid')):
                self.assertFalse(approved.includes(row | changes,campaign_member=True))

    def test_multiple_campaigns_are_explicit_and_all_assigned_agents_are_eligible(self):
        other=uuid4()
        value=screening_policy() | dict(version=4,scope='campaign',enabled=True,
            audio_approved=True,screening_approved=True,campaign_ids=[str(vm.PILOT_CAMPAIGN),str(other)])
        value.pop('campaign_id')
        approved=vm.Pilot.parse(value)
        self.assertEqual(approved.campaigns,frozenset({vm.PILOT_CAMPAIGN,other}))
        for campaign in approved.campaigns:
            for _ in range(20):
                row=dict(actor_id=uuid4(),contact_id=uuid4(),campaign_id=campaign,
                    destination='+14165550101',dialer_generation=1,state='authorized')
                self.assertFalse(approved.includes(row))
                self.assertTrue(approved.includes(row,campaign_member=True))
                for changes in (dict(campaign_id=uuid4()),dict(contact_id=None),
                        dict(dialer_generation=None),dict(state='finished')):
                    self.assertFalse(approved.includes(row | changes,campaign_member=True))

    def test_multiple_campaigns_cannot_enable_wildcards_or_implicit_scope(self):
        value=screening_policy() | dict(version=4,scope='campaign',enabled=True,
            audio_approved=True,screening_approved=True,campaign_ids=[str(uuid4())])
        value.pop('campaign_id')
        for changes in (dict(campaign_ids=[]),dict(campaign_ids='all'),dict(campaign_ids=['*']),
                dict(campaign_ids=[value['campaign_ids'][0]]*2),dict(campaign_ids=[str(uuid4()) for _ in range(21)]),
                dict(campaign_id=str(vm.PILOT_CAMPAIGN)),dict(version=3),dict(version=True),
                dict(scope='all'),dict(audio_approved=False),dict(screening_approved=False),
                dict(agent_ids=[str(uuid4())]),dict(test_numbers=['+14165550101'])):
            with self.subTest(changes=changes),self.assertRaises(vm.ProtocolError):
                vm.Pilot.parse(value | changes)
        approved=vm.Pilot.parse(value)
        self.assertNotIn(vm.PILOT_CAMPAIGN,approved.campaigns)

    def test_campaign_scope_cannot_be_implicitly_selected_or_mix_allowlists(self):
        value=screening_policy() | dict(version=3,scope='campaign',enabled=True,
            audio_approved=True,screening_approved=True)
        for changes in (dict(scope='all'),dict(version=2),dict(mode='observe'),
                dict(audio_approved=False),dict(screening_approved=False),
                dict(agent_ids=[str(uuid4())]),dict(test_numbers=['+14165550101'])):
            with self.subTest(changes=changes), self.assertRaises(vm.ProtocolError):
                vm.Pilot.parse(value | changes)

    def test_screening_is_separately_disabled_and_requires_approval(self):
        inactive=vm.Pilot.parse(screening_policy())
        self.assertFalse(inactive.enabled)
        self.assertEqual(inactive.mode,'screen')
        value=screening_policy(enabled=True,agent_ids=[str(uuid4())],
            test_numbers=['+14165550101'],audio_approved=True)
        with self.assertRaises(vm.ProtocolError):vm.Pilot.parse(value)
        approved=vm.Pilot.parse(value | {'screening_approved':True})
        self.assertTrue(approved.screening_approved)
        row=dict(actor_id=next(iter(approved.agents)),campaign_id=vm.PILOT_CAMPAIGN,
            destination='+14165550101',dialer_generation=1,state='authorized')
        self.assertTrue(approved.includes(row))
        self.assertFalse(approved.includes(row | {'state':'finished'}))
        self.assertFalse(approved.includes(row | {'dialer_generation':None}))
        with self.assertRaises(vm.ProtocolError):vm.Pilot.parse(value | {'screening_approved':'true'})

    def test_only_explicit_machine_or_beep_with_confirmed_stop_can_hang_up(self):
        for status,cause in [('MACHINE','MACHINE'),('MACHINE','MACHINE_BEEP')]:
            self.assertEqual(vm.screen_action(vm.Result(status,cause),stop_confirmed=True),'hangup')
            for stopped in (False,None,1,'true'):
                self.assertEqual(vm.screen_action(vm.Result(status,cause),stop_confirmed=stopped),'continue')
        for status,cause in [('MACHINE','INITIALSILENCE'),('MACHINE','MAXWORD'),('MACHINE','MACHINE_STATIC'),
                ('MACHINE','DISCONNECT'),('MACHINE','CALLGUARD'),('CALLGUARD','CALLGUARD'),
                ('HUMAN','HUMAN'),('FAILED','LIMIT_REACHED'),('FAILED','AUTH_FAILED'),
                ('FAILED','CPS_LIMIT'),('FAILED','transport_or_protocol'),('MACHINE','future')]:
            self.assertEqual(vm.screen_action(vm.Result(status,cause),stop_confirmed=True),'continue')

    def test_screening_keeps_original_dial_recording_and_does_not_enable_twilio_amd(self):
        identifier=uuid4()
        legacy=ET.fromstring(controlled_call_twiml(PROFILE,identifier,'+14165550101'))
        screened=ET.fromstring(controlled_call_twiml(PROFILE,identifier,'+14165550101',screening=True))
        self.assertEqual(legacy.find('Dial').attrib,screened.find('Dial').attrib)
        normal=legacy.find('Dial/Number');new=screened.find('Dial/Number')
        self.assertNotIn('url',normal.attrib)
        self.assertEqual(new.attrib['url'],webhook_url(PROFILE,'screen-start',identifier))
        self.assertEqual(new.attrib['method'],'POST')
        self.assertEqual({k:v for k,v in new.attrib.items() if k not in {'url','method'}},normal.attrib)
        self.assertNotIn('machineDetection',new.attrib)
        self.assertEqual(screened.find('Dial').attrib['answerOnBridge'],'true')
        self.assertEqual(screened.find('Dial').attrib['record'],'record-from-answer-dual')

    def test_greeting_uses_only_supported_whisper_verbs_and_no_speech_collection(self):
        identifier=uuid4();xml=ET.fromstring(screen.greeting(PROFILE,identifier))
        self.assertEqual([child.tag for child in xml],['Gather'])
        wait=xml.find('Gather')
        self.assertEqual(wait.attrib['input'],'dtmf')
        self.assertEqual(wait.attrib['timeout'],'1')
        self.assertEqual(wait.attrib['finishOnKey'],'')
        self.assertEqual(wait.attrib['actionOnEmptyResult'],'true')
        self.assertEqual(wait.attrib['action'],webhook_url(PROFILE,'screen-result',identifier))
        self.assertEqual(wait.find('Say').text,screen.GREETING)
        self.assertIn('Maisonverte Québec',wait.find('Say').text)
        self.assertEqual(wait.find('Say').attrib,{'language':'fr-CA','voice':'Polly.Chantal'})
        self.assertEqual(list(ET.fromstring(screen.empty())),[])
        self.assertEqual([child.tag for child in ET.fromstring(screen.reject())],['Hangup'])

    def test_controlled_test_profile_and_non_boolean_flag_cannot_enable_screening(self):
        controlled=ControlledVoiceProfile(PROFILE.account_sid,PROFILE.api_key_sid,PROFILE.api_key_secret,
            PROFILE.twiml_app_sid,PROFILE.shared_key_id,PROFILE.shared_key_secret,
            PROFILE.public_origin,PROFILE.caller_number,'+14165550101')
        with self.assertRaises(VoiceConfigurationError):controlled_call_twiml(controlled,uuid4(),screening=True)
        with self.assertRaises(VoiceConfigurationError):controlled_call_twiml(PROFILE,uuid4(),'+14165550101',screening=1)

    def test_new_callback_signatures_bind_child_account_kind_and_intent(self):
        identifier=uuid4();settings='key='+PROFILE.shared_key_id+',algorithm=HMAC_SHA1'
        values=FormData([('AccountSid',PROFILE.account_sid),('CallSid','CA'+'1'*32),
                         ('ParentCallSid','CA'+'2'*32),('Digits','')])
        for kind in ('screen-start','screen-result'):
            signature=RequestValidator(PROFILE.shared_key_secret).compute_signature(webhook_url(PROFILE,kind,identifier),values)
            args=dict(profile=PROFILE,kind=kind,intent_id=identifier,body=urlencode(values.multi_items()).encode(),
                content_type='application/x-www-form-urlencoded',signature=signature,signing_settings=settings)
            self.assertEqual(authenticate_webhook(**args)['CallSid'],'CA'+'1'*32)
            with self.assertRaises(VoiceWebhookError):authenticate_webhook(**(args | {'intent_id':uuid4()}))
            changed=FormData([*values.multi_items(),('Digits','1')])
            signed=RequestValidator(PROFILE.shared_key_secret).compute_signature(webhook_url(PROFILE,kind,identifier),changed)
            with self.assertRaises(VoiceWebhookError):
                authenticate_webhook(**(args | {'body':urlencode(changed.multi_items()).encode(),'signature':signed}))

    def test_absent_or_observation_policy_never_enables_screening(self):
        with patch.dict(os.environ,{},clear=True):self.assertIsNone(screen.configured())
        with patch.dict(os.environ,{'VMHUNTER_PILOT_FILE':'synthetic'}), \
                patch.object(screen,'policy_from_file',return_value=vm.Pilot.parse(policy())):
            self.assertIsNone(screen.configured())


class ScreeningHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status=202;self.answer={'accepted':True};self.requests=[];self.redirect=False
        async def admit(request):
            self.requests.append(await request.json())
            if self.redirect:return web.Response(status=302,headers={'Location':'/another'})
            return web.json_response(self.answer,status=self.status)
        app=web.Application();app.router.add_post('/private/observe',admit)
        self.server=TestServer(app);await self.server.start_server()
        self.rpc=patch.object(screen,'RPC_URL',str(self.server.make_url('/private/observe')));self.rpc.start()

    async def asyncTearDown(self):self.rpc.stop();await self.server.close()

    async def test_internal_start_needs_explicit_admission_and_signed_purpose(self):
        identifier=uuid4();pilot_id=str(uuid4());call='CA'+'1'*32
        self.assertTrue(await screen.request_analysis(PROFILE,identifier,call,pilot_id))
        payload=vm.unticket(PROFILE.shared_key_secret,'dispatch',self.requests[0]['ticket'])
        self.assertEqual(payload,dict(intent_id=str(identifier),call_sid=call,pilot_id=pilot_id))
        self.answer={'accepted':False}
        self.assertFalse(await screen.request_analysis(PROFILE,identifier,call,pilot_id))
        self.answer={'accepted':'true'}
        self.assertFalse(await screen.request_analysis(PROFILE,identifier,call,pilot_id))
        self.answer={'accepted':1}
        self.assertFalse(await screen.request_analysis(PROFILE,identifier,call,pilot_id))

    async def test_rejection_redirect_and_oversized_reply_fall_back_without_call_control(self):
        for status,reply in [(401,{'private':'do not echo'}),(202,{'padding':'x'*200})]:
            self.status,self.answer=status,reply
            self.assertFalse(await screen.request_analysis(PROFILE,uuid4(),'CA'+'1'*32,str(uuid4())))
        self.redirect=True
        self.assertFalse(await screen.request_analysis(PROFILE,uuid4(),'CA'+'1'*32,str(uuid4())))

    async def test_screening_policy_does_not_also_launch_after_answer_observation(self):
        pilot=vm.Pilot.parse(screening_policy(enabled=True,agent_ids=[str(uuid4())],
            test_numbers=['+14165550101'],audio_approved=True) | {'screening_approved':True})
        with patch.dict(os.environ,{'VMHUNTER_PILOT_FILE':'synthetic'}), \
                patch.object(observer,'policy_from_file',return_value=pilot), \
                patch.object(observer.aiohttp,'ClientSession') as network:
            await observer.dispatch(PROFILE,uuid4(),{'CallStatus':'in-progress','CallSid':'CA'+'1'*32})
            network.assert_not_called()

    async def test_database_failure_allows_bridge_but_authentication_failure_is_not_hidden(self):
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=object())))
        for function,operation in [(screen.start,'begin'),(screen.finish,'complete')]:
            with patch.object(screen,operation,side_effect=SQLAlchemyError('private database details')), \
                    self.assertLogs(screen.log,level='WARNING') as logged:
                self.assertEqual(ET.fromstring(await function(request,PROFILE,uuid4(),{})).tag,'Response')
                self.assertNotIn('private database details',str(logged.output))
            with patch.object(screen,operation,side_effect=HTTPException(403,'not authorized')):
                with self.assertRaises(HTTPException):await function(request,PROFILE,uuid4(),{})
            with patch.object(screen,operation,side_effect=IntegrityError('private statement',{},Exception())):
                with self.assertRaises(HTTPException) as caught:await function(request,PROFILE,uuid4(),{})
                self.assertEqual(caught.exception.status_code,403)


if __name__=='__main__':unittest.main()

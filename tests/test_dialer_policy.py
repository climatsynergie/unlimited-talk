"""Calling configuration and provider inventory reject ambiguous routing."""
from dataclasses import asdict
import importlib.util
from pathlib import Path
import re
import sys
import unittest
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from app.telephony.dialer_policy import CallingSettings,RegionRule
from app.telephony.caller_directory import NumberReader,DirectoryError,page_suffix
from app.telephony.twilio_voice import ManualVoiceProfile,controlled_call_twiml
from xml.etree import ElementTree


class DialerPolicyTests(unittest.TestCase):
    def test_campaign_activation_needs_owned_number_and_nonoverlapping_hours(self):
        number=uuid4()
        base=dict(request_id=uuid4(),version=0,enabled=True,default_number_id=number,
            hours=[dict(weekday=0,start=540,end=1020)])
        self.assertTrue(CallingSettings(**base).enabled)
        self.assertEqual(CallingSettings(**(base|dict(hours=[]))).hours, [])
        for invalid in [dict(default_number_id=None),dict(hours=[dict(weekday=0,start=600,end=500)]),
            dict(hours=[dict(weekday=0,start=540,end=1020),dict(weekday=0,start=600,end=1080)]),dict(enabled=1)]:
            with self.subTest(invalid=invalid),self.assertRaises(ValidationError):CallingSettings(**(base|invalid))
        rule=dict(number_id=number,country='ca',prefix='+1514')
        self.assertEqual(RegionRule(**rule).country,'CA')
        for invalid in [dict(country='',prefix=''),dict(country='ZZ'),dict(prefix='514'),dict(prefix='+1514 ext2')]:
            with self.assertRaises(ValidationError):RegionRule(**(rule|invalid))
        with self.assertRaises(ValidationError):CallingSettings(**(base|dict(rules=[rule,rule])))

    def test_shared_profile_renders_only_the_frozen_reservation_caller(self):
        profile=ManualVoiceProfile('AC'+'a'*32,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
            'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100')
        xml=ElementTree.fromstring(controlled_call_twiml(profile,uuid4(),'+14165550110','+442079460002'))
        self.assertEqual(xml.find('Dial').get('callerId'),'+442079460002')
        self.assertEqual(xml.find('Dial/Number').text,'+14165550110')


class NumberDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.profile=ManualVoiceProfile('AC'+'a'*32,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
            'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100')
        self.number=dict(account_sid=self.profile.account_sid,sid='PN'+'1'*32,phone_number='+14165550100',
            friendly_name='Montréal',capabilities=dict(voice=True,sms=True),status='in-use')
        self.base='/2010-04-01/Accounts/'+self.profile.account_sid+'/IncomingPhoneNumbers.json'

    def test_provider_list_is_read_only_account_bound_and_paginated(self):
        requests=[]
        pages=[dict(incoming_phone_numbers=[self.number],next_page_uri=self.base+'?PageSize=100&Page=1&PageToken=a%2Bb%3D'),
               dict(incoming_phone_numbers=[self.number|dict(sid='PN'+'2'*32,phone_number='+442079460002')],next_page_uri=None)]
        def send(request):
            self.assertEqual(request.method,'GET');requests.append(request.full_url);return pages.pop(0)
        result=NumberReader(self.profile,send).read()
        self.assertEqual(len(result),2)
        self.assertTrue(all(n['voice_enabled'] for n in result))
        self.assertEqual(requests[1].split('?',1)[1],'PageSize=100&Page=1&PageToken=a%2Bb%3D')

    def test_untrusted_page_urls_and_query_overrides_are_refused(self):
        for suffix in ['https://untrusted.invalid'+self.base+'?PageSize=100&Page=1&PageToken=x',
            self.base.replace(self.profile.account_sid,'AC'+'b'*32)+'?PageSize=100&Page=1&PageToken=x',
            self.base+'?PageSize=100&Page=1&PageToken=x&PageToken=y',
            self.base+'?PageSize=100&Page=1&PageToken=x&CallbackUrl=https://untrusted.invalid',
            self.base+'?PageSize=100&Page=1&PageToken=%0A']:
            with self.subTest(suffix=suffix),self.assertRaises(DirectoryError):page_suffix(self.profile.account_sid,suffix)

    def test_a_partial_or_foreign_inventory_never_becomes_an_owned_caller(self):
        for change in [dict(account_sid='AC'+'b'*32),dict(sid='CA'+'1'*32),dict(phone_number='sip:untrusted.invalid'),dict(capabilities=dict(voice=1))]:
            with self.subTest(change=change),self.assertRaises(DirectoryError):
                NumberReader(self.profile,lambda _:dict(incoming_phone_numbers=[self.number|change],next_page_uri=None)).read()
        with self.assertRaises(DirectoryError):
            NumberReader(self.profile,lambda _:dict(incoming_phone_numbers=[self.number,self.number],next_page_uri=None)).read()

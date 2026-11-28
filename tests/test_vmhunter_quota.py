"""Explicit subscription quota must preserve opt-in and legacy canary limits."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4
from app.telephony import vmhunter as vm
from app.telephony.vmhunter_observer import ProviderQuota,Store
from test_vmhunter import PROFILE,policy

class QuotaTests(unittest.TestCase):
    def pilot(self):
        value=policy(version=3,scope='campaign',mode='screen',enabled=True,
            audio_approved=True,screening_approved=True)
        return vm.Pilot.parse(value)
    def test_no_configuration_preserves_the_existing_canary_budget(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertIsNone(ProviderQuota.from_environment(self.pilot()))
        self.assertIsNone(Store(None,PROFILE,self.pilot()).provider_quota)
    def test_free_subscription_is_explicit_and_works_while_worker_drains(self):
        from dataclasses import replace
        env={'VMHUNTER_QUOTA_SOURCE':'provider','VMHUNTER_MONTHLY_ALLOWANCE':'5000'}
        for enabled in (True,False):
            with patch.dict(os.environ,env,clear=True):
                quota=ProviderQuota.from_environment(replace(self.pilot(),enabled=enabled))
            self.assertEqual(quota.monthly_allowance,5000)
    def test_partial_invalid_or_unknown_plan_configuration_cannot_silently_expand(self):
        for env in ({'VMHUNTER_QUOTA_SOURCE':'provider'}, {'VMHUNTER_MONTHLY_ALLOWANCE':'5000'},
                {'VMHUNTER_QUOTA_SOURCE':'all','VMHUNTER_MONTHLY_ALLOWANCE':'5000'},
                {'VMHUNTER_QUOTA_SOURCE':'provider','VMHUNTER_MONTHLY_ALLOWANCE':'500'},
                {'VMHUNTER_QUOTA_SOURCE':'provider','VMHUNTER_MONTHLY_ALLOWANCE':'300000'}):
            with self.subTest(env=env),patch.dict(os.environ,env,clear=True),self.assertRaises(ValueError):
                ProviderQuota.from_environment(self.pilot())
        for count in (True,500,5000.0,'5000',300000):
            with self.subTest(count=count),self.assertRaises(ValueError):ProviderQuota(count)
    def test_subscription_quota_cannot_override_unapproved_or_narrow_test_scope(self):
        from dataclasses import replace
        pilot=self.pilot()
        for value in (replace(pilot,scope='pilot'),replace(pilot,mode='observe'),
                replace(pilot,audio_approved=False),replace(pilot,screening_approved=False)):
            with self.subTest(value=value),self.assertRaises(ValueError):
                Store(None,PROFILE,value,provider_quota=ProviderQuota())
        with self.assertRaises(ValueError):Store(None,PROFILE,pilot,provider_quota=True)

    def test_audio_diagnostics_reject_raw_content_and_invalid_unbounded_counters(self):
        from uuid import uuid4
        pilot=self.pilot();store=Store(None,PROFILE,pilot)
        payload=dict(intent_id=str(uuid4()),call_sid='CA'+'a'*32,pilot_id=str(pilot.identifier),nonce='b'*32)
        for stats in ({'raw_audio':'private'},dict(pcm_bytes=320,frames=True,signal_frames=0),
                dict(pcm_bytes=320,frames=1,signal_frames=2),dict(pcm_bytes=1,frames=1,signal_frames=0),
                dict(pcm_bytes=320*176,frames=176,signal_frames=1)):
            with self.subTest(stats=stats),self.assertRaises(ValueError):
                store.result(payload,vm.Result('MACHINE','INITIALSILENCE'),stop_confirmed=True,audio_stats=stats)

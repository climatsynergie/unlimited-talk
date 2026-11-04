"""Manual profiles bind provider identity, never a recipient whitelist."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from xml.etree import ElementTree

import jwt
from fastapi import HTTPException
from app.telephony.configuration import load_profile
from app.telephony.service import profile_hash, validate_destination
from app.telephony.reconciliation import PendingCall, ProviderReadError
from app.telephony.twilio_voice import ManualVoiceProfile, VoiceConfigurationError, browser_token, controlled_call_twiml


class ManualVoiceTests(unittest.TestCase):
    def setUp(self):
        self.profile = ManualVoiceProfile('AC'+'a'*32, 'SK'+'b'*32, 'c'*32, 'AP'+'d'*32,
            'webhooks_sharedkey_'+'e'*26, 'f'*32, 'https://voice.example.invalid', '+14165550100')

    def test_recipient_is_explicit_and_cannot_be_the_caller_or_an_extension(self):
        for number in ['+14165550101', '+14165550102', '+442079460001']:
            self.assertEqual(validate_destination(number, self.profile), number)
            xml = ElementTree.fromstring(controlled_call_twiml(self.profile, uuid4(), number))
            self.assertEqual(xml.find('Dial/Number').text, number)
            self.assertEqual(xml.find('Dial').get('timeLimit'), '1800')
        for bad in [None, '', self.profile.caller_number, '+14165550101\n', '+14165550101ext2', '14165550101']:
            with self.subTest(bad=bad), self.assertRaises(HTTPException):
                validate_destination(bad, self.profile)
            with self.assertRaises(VoiceConfigurationError):
                controlled_call_twiml(self.profile, uuid4(), bad)

    def test_capacity_changes_do_not_orphan_pending_calls_or_archive_jobs(self):
        binding = profile_hash(self.profile)
        self.assertEqual(profile_hash(replace(self.profile, max_concurrent_calls=3, max_duration_seconds=300)), binding)
        self.assertNotEqual(profile_hash(replace(self.profile, caller_number='+14165550103')), binding)
        pending = PendingCall(uuid4(), uuid4(), binding, self.profile.account_sid,
            self.profile.caller_number, '+14165550104', 'CA'+'1'*32, None)
        pending.check(self.profile)
        with self.assertRaises(ProviderReadError):
            replace(pending, destination=self.profile.caller_number).check(self.profile)

    def test_token_covers_setup_and_the_configured_call_but_remains_intent_scoped(self):
        token = browser_token(self.profile, uuid4(), uuid4())
        claims = jwt.decode(token, self.profile.api_key_secret, algorithms=['HS256'], issuer=self.profile.api_key_sid)
        self.assertEqual(claims['exp']-claims['nbf'], 1980)
        self.assertFalse(claims['grants']['voice'].get('incoming', {}).get('allow', False))
        for key in ['max_concurrent_calls', 'max_duration_seconds']:
            for value in [True, 0, 10000]:
                with self.assertRaises(VoiceConfigurationError):
                    replace(self.profile, **{key: value})

    def test_private_v2_profile_is_strict_and_cannot_arm_the_legacy_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'profile.json'
            path.write_text(json.dumps(dict(version=2, mode='manual', **asdict(self.profile))))
            path.chmod(0o600)
            env = dict(APP_ENV='staging', DB_USER='ut_staging_runtime', DB_NAME='unlimited_talk_staging',
                APP_ORIGIN=self.profile.public_origin, VOICE_TEST_PROFILE_FILE=str(path))
            for mode in ['manual', 'webhooks_only', 'recovery_only']:
                with patch.dict(os.environ, {**env, 'COMMUNICATIONS_MODE': mode}, clear=True):
                    self.assertEqual(load_profile(), self.profile)
            with patch.dict(os.environ, {**env, 'COMMUNICATIONS_MODE': 'controlled_test'}, clear=True):
                with self.assertRaises(RuntimeError):
                    load_profile()
            value = json.loads(path.read_text()); value['approved_destination'] = '+14165550101'
            path.write_text(json.dumps(value))
            with patch.dict(os.environ, {**env, 'COMMUNICATIONS_MODE': 'manual'}, clear=True):
                with self.assertRaises(RuntimeError):
                    load_profile()

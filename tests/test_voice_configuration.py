"""Only a complete private, origin-bound controlled profile can arm Voice."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.telephony.configuration import load_profile


class VoiceConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'profile.json'
        self.value = dict(version=1, mode='controlled_test', account_sid='AC'+'a'*32,
            api_key_sid='SK'+'b'*32, api_key_secret='c'*32, twiml_app_sid='AP'+'d'*32,
            shared_key_id='webhooks_sharedkey_'+'e'*26, shared_key_secret='f'*32,
            public_origin='https://voice.example.invalid', caller_number='+14165550100', approved_destination='+14165550101')
        self.path.write_text(json.dumps(self.value)); self.path.chmod(0o600)
        self.env = dict(APP_ENV='staging', DB_USER='ut_staging_runtime', DB_NAME='unlimited_talk_staging',
                        COMMUNICATIONS_MODE='controlled_test', VOICE_TEST_PROFILE_FILE=str(self.path),
                        APP_ORIGIN=self.value['public_origin'])

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_controlled_profile_loads_and_disabled_mode_never_reads_secrets(self):
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual(load_profile().approved_destination,self.value['approved_destination'])
        for mode in ['webhooks_only','recovery_only']:
            with patch.dict(os.environ,{**self.env,'COMMUNICATIONS_MODE':mode},clear=True):
                self.assertEqual(load_profile().approved_destination,self.value['approved_destination'])
        self.path.unlink()
        with patch.dict(os.environ,{**self.env,'COMMUNICATIONS_MODE':'disabled'},clear=True):
            self.assertIsNone(load_profile())

    def test_unknown_mode_role_environment_and_origin_fail_closed(self):
        for change in [dict(COMMUNICATIONS_MODE='live'),dict(DB_USER='ut_staging_migrator'),dict(APP_ENV='production'),
                       dict(DB_NAME='defaultdb'),dict(APP_ORIGIN='https://other.example.invalid')]:
            with self.subTest(change=change),patch.dict(os.environ,{**self.env,**change},clear=True):
                with self.assertRaises(RuntimeError):load_profile()

    def test_public_permissions_links_or_missing_profile_are_rejected_without_echo(self):
        self.path.chmod(0o644)
        with patch.dict(os.environ,self.env,clear=True),self.assertRaises(RuntimeError) as result:
            load_profile()
        self.assertNotIn(self.value['api_key_secret'],str(result.exception))
        self.path.chmod(0o600)
        link=self.path.with_name('link');link.symlink_to(self.path)
        with patch.dict(os.environ,{**self.env,'VOICE_TEST_PROFILE_FILE':str(link)},clear=True):
            with self.assertRaises(RuntimeError):load_profile()
        link.unlink();os.link(self.path,link)
        with patch.dict(os.environ,self.env,clear=True),self.assertRaises(RuntimeError):load_profile()

    def test_profile_version_schema_and_target_are_strict(self):
        for change in [dict(version=True),dict(version=2),dict(mode='live'),dict(extra=True),
                       dict(approved_destination=self.value['caller_number']),dict(shared_key_secret='short')]:
            self.path.write_text(json.dumps({**self.value,**change}))
            with self.subTest(change=change),patch.dict(os.environ,self.env,clear=True),self.assertRaises(RuntimeError):
                load_profile()

    def test_database_guard_requires_profile_and_keeps_verified_tls_and_pool_bounds(self):
        from app.database import make_engine
        password=self.path.with_name('password');password.write_text('x'*48)
        certificate=self.path.with_name('ca.crt');certificate.write_text('-----BEGIN CERTIFICATE-----\nfixture\n')
        env={**self.env,'DB_DEPLOYMENT':'managed','DB_HOST':'private-db-example.d.db.ondigitalocean.com',
             'DB_PASSWORD_FILE':str(password),'DB_SSLMODE':'verify-full','DB_SSLROOTCERT':str(certificate)}
        with patch.dict(os.environ,env,clear=True):
            engine=make_engine()
            self.assertEqual(engine.url.port,25060)
            self.assertEqual(engine.pool.size(),2)
            engine.dispose()
        self.path.unlink()
        with patch.dict(os.environ,env,clear=True),self.assertRaises(RuntimeError):make_engine()

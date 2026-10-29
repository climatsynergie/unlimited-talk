"""TwiML setup cannot update existing resources or retry an uncertain creation."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('voice_application', SCRIPTS / 'twilio_voice_application.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProviderFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'operation.json'
        self.config = dict(version=1, mode='credentials_only', region='us1', account_sid='AC' + 'a' * 32,
                           phone_number_sid='PN' + 'b' * 32, caller_number='+14165550100',
                           approved_destination='+14165550101', public_origin='https://staging.unlimitedtalkapp.com',
                           api_key_sid='SK' + 'c' * 32, api_key_secret='d' * 32, requested_key_type='standard')
        self.new_sid = 'AP' + 'e' * 32
        self.old_sid = 'AP' + 'f' * 32
        self.apps = {self.old_sid: dict(account_sid=self.config['account_sid'], sid=self.old_sid,
                                       friendly_name='Legacy', voice_url='https://legacy.example.com/voice',
                                       extra_future_setting='preserve-me')}
        self.numbers = {self.config['phone_number_sid']: dict(account_sid=self.config['account_sid'],
                        sid=self.config['phone_number_sid'], phone_number=self.config['caller_number'],
                        capabilities=dict(voice=True, sms=True), trunk_sid='TK' + '1' * 32)}
        self.requests = []
        self.fail_after_create = False
        self.fail_before_create = False
        self.provider = module.Provider(self.config, self.send)

    def tearDown(self):
        self.tmp.cleanup()

    def new_application(self):
        return dict(account_sid=self.config['account_sid'], sid=self.new_sid, friendly_name=module.NAME,
                    voice_url=module.desired(self.config)['VoiceUrl'], voice_method='POST',
                    status_callback=module.desired(self.config)['StatusCallback'], status_callback_method='POST',
                    voice_caller_id_lookup=False, public_application_connect_enabled=False,
                    voice_fallback_url=None, sms_url=None, sms_fallback_url=None,
                    sms_status_callback=None, message_status_callback=None)

    def send(self, request):
        self.requests.append(request)
        path = request.full_url.removeprefix(self.provider.base)
        if request.method == 'GET':
            if path == '/Applications.json?PageSize=1000':
                return dict(applications=copy.deepcopy(list(self.apps.values())), next_page_uri=None)
            if path == '/IncomingPhoneNumbers.json?PageSize=1000':
                return dict(incoming_phone_numbers=copy.deepcopy(list(self.numbers.values())), next_page_uri=None)
            if path == '/Applications/' + self.new_sid + '.json':
                return copy.deepcopy(self.apps[self.new_sid])
        elif request.method == 'POST' and path == '/Applications.json':
            if self.fail_before_create:
                raise TimeoutError('synthetic unknown request outcome')
            self.apps[self.new_sid] = self.new_application()
            if self.fail_after_create:
                raise TimeoutError('synthetic lost response')
            return copy.deepcopy(self.apps[self.new_sid])
        raise AssertionError('Unexpected provider operation')

    def run_action(self, action):
        return module.run(action, self.config, self.path, self.provider)

    def posts(self):
        return [r for r in self.requests if r.method == 'POST']


class VoiceApplicationTests(ProviderFixture, unittest.TestCase):
    def test_prepare_is_read_only_then_create_once_and_preserve_existing_resources(self):
        before_apps = copy.deepcopy(self.apps)
        before_numbers = copy.deepcopy(self.numbers)
        self.assertEqual(self.run_action('prepare')['state'], 'prepared')
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        result = self.run_action('apply')
        self.assertEqual(result['state'], 'verified')
        self.assertEqual(result['application_sid'], self.new_sid)
        self.assertEqual(len(self.posts()), 1)
        request = self.posts()[0]
        self.assertEqual(parse_qs(request.data.decode()), {k: [v] for k, v in module.desired(self.config).items()})
        self.assertEqual(self.apps[self.old_sid], before_apps[self.old_sid])
        self.assertEqual(self.numbers, before_numbers)
        for action in ['apply', 'prepare', 'check']:
            self.assertEqual(self.run_action(action)['state'], 'verified')
        self.assertEqual(len(self.posts()), 1)
        for field in ('public_webhooks_ready', 'calling_enabled', 'live_call_verified'):
            self.assertIs(result[field], False)
        for value in (self.config['api_key_secret'], self.config['api_key_sid'],
                      self.config['caller_number'], self.config['approved_destination']):
            self.assertNotIn(value, json.dumps(result))

    def test_lost_response_reconciles_existing_application_without_reposting(self):
        self.run_action('prepare')
        self.fail_after_create = True
        with self.assertRaises(TimeoutError):
            self.run_action('apply')
        self.assertEqual(module.read_private(self.path)['state'], 'requested')
        self.fail_after_create = False
        self.assertEqual(self.run_action('apply')['state'], 'verified')
        self.assertEqual(len(self.posts()), 1)

    def test_uncertain_request_with_no_visible_resource_never_posts_again(self):
        self.run_action('prepare')
        self.fail_before_create = True
        with self.assertRaises(TimeoutError):
            self.run_action('apply')
        self.fail_before_create = False
        for action in ['apply', 'check', 'prepare']:
            with self.assertRaises(module.PreflightError):
                self.run_action(action)
        self.assertEqual(len(self.posts()), 1)

    def test_journal_is_durable_before_provider_effect(self):
        self.run_action('prepare')
        original = self.send

        def send(request):
            if request.method == 'POST':
                self.assertEqual(module.read_private(self.path)['state'], 'requested')
            return original(request)

        self.provider.send = send
        self.run_action('apply')

    def test_name_collision_cannot_adopt_existing_application(self):
        self.apps[self.old_sid]['friendly_name'] = module.NAME
        with self.assertRaises(module.PreflightError):
            self.run_action('prepare')
        self.assertEqual(self.posts(), [])
        self.assertFalse(self.path.exists())

    def test_drift_before_or_after_create_is_detected_without_repairing_existing_resources(self):
        self.run_action('prepare')
        self.apps[self.old_sid]['extra_future_setting'] = 'changed'
        with self.assertRaises(module.PreflightError):
            self.run_action('apply')
        self.assertEqual(self.posts(), [])
        self.apps[self.old_sid]['extra_future_setting'] = 'preserve-me'
        self.run_action('apply')
        self.numbers[self.config['phone_number_sid']]['trunk_sid'] = None
        with self.assertRaises(module.PreflightError):
            self.run_action('check')
        self.assertEqual(len(self.posts()), 1)

    def test_changed_plan_cannot_reuse_journal_and_missing_prepare_cannot_write(self):
        with self.assertRaises(FileNotFoundError):
            self.run_action('apply')
        self.assertEqual(self.posts(), [])
        self.run_action('prepare')
        with self.assertRaises(module.PreflightError):
            module.run('apply', {**self.config, 'approved_destination': '+14165550102'}, self.path, self.provider)
        self.assertEqual(self.posts(), [])

    def test_bad_provider_configuration_or_unexpected_inbound_routes_fail_verification(self):
        self.run_action('prepare')
        original = self.new_application
        self.new_application = lambda: {**original(), 'sms_url': 'https://foreign.example.com/sms'}
        with self.assertRaises(module.PreflightError):
            self.run_action('apply')
        self.assertEqual(module.read_private(self.path)['state'], 'created')
        with self.assertRaises(module.PreflightError):
            self.run_action('apply')
        self.assertEqual(len(self.posts()), 1)

    def test_only_allowed_methods_and_paths_can_reach_transport(self):
        for method, path, fields in [('POST', '/Calls.json', {}), ('POST', '/IncomingPhoneNumbers.json', {}),
                                     ('POST', '/Applications/' + self.old_sid + '.json', {}),
                                     ('DELETE', '/Applications/' + self.old_sid + '.json', None),
                                     ('GET', '//foreign.example.com', None),
                                     ('POST', '/Applications.json', {'FriendlyName': 'wrong'}),
                                     ('GET', '/Applications.json?PageSize=1000', {'unexpected': True})]:
            with self.subTest(method=method, path=path), self.assertRaises(module.PreflightError):
                self.provider.request(method, path, fields)
        self.assertEqual(self.requests, [])

    def test_missing_inventory_page_or_foreign_account_blocks_prepare(self):
        self.provider.send = lambda request: dict(applications=[], next_page_uri='https://foreign.example.com')
        with self.assertRaises(module.PreflightError):
            self.run_action('prepare')
        self.provider.send = self.send
        self.apps[self.old_sid]['account_sid'] = 'AC' + '9' * 32
        with self.assertRaises(module.PreflightError):
            self.run_action('prepare')
        self.assertEqual(self.posts(), [])

    def test_private_journal_links_and_permissions_are_rejected(self):
        self.run_action('prepare')
        self.path.chmod(0o640)
        with self.assertRaises(module.PreflightError):
            self.run_action('apply')
        self.path.chmod(0o600)
        link = self.path.with_name('linked.json')
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            module.run('apply', self.config, link, self.provider)
        self.assertEqual(self.posts(), [])

    def test_unprivileged_cli_cannot_read_keys_or_mutate_provider(self):
        output = io.StringIO()
        with patch.object(module.os, 'geteuid', return_value=10001), patch.object(module.voice, 'load_base') as load, \
                contextlib.redirect_stderr(output):
            self.assertEqual(module.main(['apply']), 1)
        load.assert_not_called()
        self.assertNotIn(self.config['api_key_secret'], output.getvalue())


if __name__ == '__main__':
    unittest.main()

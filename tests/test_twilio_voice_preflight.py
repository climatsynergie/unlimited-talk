"""Voice credential isolation and redaction; synthetic credentials, no network."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('voice_preflight', SCRIPTS / 'twilio_voice_preflight.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VoicePreflightTests(unittest.TestCase):
    def setUp(self):
        self.base = dict(version=1, mode='read_only', region='us1', account_sid='AC' + 'a' * 32,
                         api_key_sid='SK' + 'b' * 32, api_key_secret='c' * 32,
                         phone_number_sid='PN' + 'd' * 32, caller_number='+14165550100')
        self.request = dict(approved_destination='+14165550101', public_origin=module.PUBLIC_ORIGIN)
        self.plan = module.prepare_plan(self.request, self.base)
        self.credentials = dict(**self.plan, requested_key_type='standard', api_key_sid='SK' + 'e' * 32,
                                api_key_secret='f' * 32)

    def test_only_selected_resource_is_read_with_new_key_and_report_is_redacted(self):
        sent = []

        def send(request):
            sent.append(request)
            return dict(account_sid=self.base['account_sid'], sid=self.base['phone_number_sid'],
                        phone_number=self.base['caller_number'], capabilities=dict(voice=True, sms=True))

        report = module.check(self.credentials, self.plan, self.base, send)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].method, 'GET')
        self.assertTrue(sent[0].full_url.endswith('/IncomingPhoneNumbers/' + self.base['phone_number_sid'] + '.json'))
        self.assertIsNone(sent[0].data)
        for field in ('configuration_changed', 'calling_enabled', 'key_type_verified',
                      'twiml_application_prepared', 'sdk_token_acceptance_verified', 'live_call_verified'):
            self.assertIs(report[field], False)
        output = json.dumps(report)
        for value in (self.base['account_sid'], self.credentials['api_key_sid'],
                      self.credentials['api_key_secret'], self.plan['approved_destination'], self.plan['caller_number']):
            self.assertNotIn(value, output)

    def test_plan_cannot_enable_calls_or_change_verified_account_or_target_origin(self):
        for change in (dict(mode='live'), dict(account_sid='AC' + 'e' * 32), dict(caller_number='+14165550102'),
                       dict(phone_number_sid='PN' + 'e' * 32), dict(public_origin='https://app.unlimitedtalkapp.com'),
                       dict(approved_destination=self.plan['caller_number']), dict(approved_destination='invalid'),
                       dict(unexpected=True), dict(version=True)):
            with self.subTest(change=change), self.assertRaises(module.PreflightError):
                module.validate_plan({**self.plan, **change}, self.base)

    def test_reused_restricted_key_or_changed_destination_is_rejected_before_network(self):
        for change in (dict(api_key_sid=self.base['api_key_sid']), dict(api_key_secret='short'),
                       dict(approved_destination='+14165550102'), dict(requested_key_type='main'), dict(extra='x')):
            with self.subTest(change=change), patch.object(module, 'check_number') as send:
                with self.assertRaises(module.PreflightError):
                    module.check({**self.credentials, **change}, self.plan, self.base)
                send.assert_not_called()

    def test_invisible_entry_confirmations_and_secret_whitespace(self):
        for values in ([self.credentials['api_key_sid'], 'f' * 32, 'mismatch'],
                       [self.credentials['api_key_sid'], ' f' * 32, ' f' * 32]):
            with self.subTest(values=values), self.assertRaises(module.PreflightError):
                iterator = iter(values)
                module.collect(self.plan, self.base, lambda label: next(iterator))
        values = iter([self.credentials['api_key_sid'], self.credentials['api_key_secret'], self.credentials['api_key_secret']])
        self.assertEqual(module.collect(self.plan, self.base, lambda label: next(values)), self.credentials)

    def test_private_store_preserves_existing_file_and_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'voice.json'
            module.write_private(self.credentials, path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                module.write_private({**self.credentials, 'api_key_secret': 'x' * 32}, path)
            self.assertEqual(module.read_private(path), self.credentials)
            link = path.with_name('link.json')
            link.symlink_to(path)
            with self.assertRaises(OSError):
                module.read_private(link)

    def test_cli_refuses_unprivileged_entry_and_redacts_unexpected_errors(self):
        with patch.object(module.os, 'geteuid', return_value=10001), patch.object(module, 'load_base') as load:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(module.main(['store']), 1)
            load.assert_not_called()
        output = io.StringIO()
        with patch.object(module.os, 'geteuid', return_value=0), patch.object(module, 'load_base', return_value=self.base), \
                patch.object(module, 'read_private', side_effect=[self.plan, self.credentials]), \
                patch.object(module, 'check', side_effect=RuntimeError(self.credentials['api_key_secret'])), \
                contextlib.redirect_stderr(output):
            self.assertEqual(module.main(['check']), 1)
        self.assertNotIn(self.credentials['api_key_secret'], output.getvalue())


if __name__ == '__main__':
    unittest.main()

import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from app.identity import bootstrap


class BootstrapValidationTests(unittest.TestCase):
    def test_invalid_password_and_mismatch_retry_without_echoing_secrets(self):
        valid='Une longue phrase personnelle de test 2026!'
        short='short'
        wrong='Une confirmation différente pour ce test!'
        output=io.StringIO()
        with patch.object(bootstrap.getpass,'getpass',side_effect=[short,valid,wrong,valid,valid]),contextlib.redirect_stdout(output):
            self.assertEqual(bootstrap.read_password(),valid)
        self.assertIn('12 et 128',output.getvalue())
        self.assertIn('différents',output.getvalue())
        for secret in [short,valid,wrong]: self.assertNotIn(secret,output.getvalue())

    def test_console_adapter_handles_previous_image_validation_without_traceback(self):
        path=Path(__file__).resolve().parents[1]/'scripts/bootstrap-staging-admin.py'
        spec=importlib.util.spec_from_file_location('bootstrap_launcher',path)
        launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
        output=io.StringIO()
        with patch.object(bootstrap,'main',side_effect=[ValueError('Le mot de passe doit contenir entre 12 et 128 caractères'),None]) as run,contextlib.redirect_stdout(output):
            exec(launcher.CONSOLE,{})
        self.assertEqual(run.call_count,2)
        self.assertIn('Recommencez',output.getvalue())
        self.assertNotIn('Traceback',output.getvalue())

    def test_console_adapter_does_not_echo_unexpected_errors(self):
        path=Path(__file__).resolve().parents[1]/'scripts/bootstrap-staging-admin.py'
        spec=importlib.util.spec_from_file_location('bootstrap_launcher',path)
        launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
        with patch.object(bootstrap,'main',side_effect=ValueError('confidential configuration')):
            with self.assertRaises(SystemExit) as error: exec(launcher.CONSOLE,{})
        self.assertNotIn('confidential',str(error.exception))

"""Secret-storage boundaries, using synthetic keys and disposable files only."""
import contextlib
import getpass
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings

source = Path(__file__).resolve().parents[1] / 'scripts/store_vmhunter_credentials.py'
spec = importlib.util.spec_from_file_location('vmhunter_credentials', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VMHunterCredentialTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'credentials.json'
        self.key = 'SYNTHETIC-VM-KEY-ONLY-' + 'x' * 40
        self.value = dict(version=1, mode='credentials_only',
                          endpoint=module.ENDPOINT, api_key=self.key)

    def test_private_round_trip_and_existing_credentials_cannot_be_overwritten(self):
        module.store(self.value, self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(module.load(self.path), self.value)
        with self.assertRaises(FileExistsError):
            module.store({**self.value, 'api_key': 'other-synthetic-key'}, self.path)
        self.assertEqual(module.load(self.path), self.value)

    def test_symlinks_hardlinks_fifos_and_insecure_permissions_are_rejected(self):
        module.store(self.value, self.path)
        link = self.path.with_name('link')
        link.symlink_to(self.path)
        with self.assertRaises(FileExistsError): module.store(self.value, link)
        with self.assertRaises(OSError): module.load(link)
        hardlink = self.path.with_name('hardlink')
        os.link(self.path, hardlink)
        with self.assertRaises(module.CredentialError): module.load(self.path)
        hardlink.unlink()
        fifo = self.path.with_name('fifo')
        os.mkfifo(fifo, 0o600)
        with self.assertRaises(module.CredentialError): module.load(fifo)
        self.path.chmod(0o644)
        with self.assertRaises(module.CredentialError): module.load(self.path)

    def test_untrusted_parent_and_symlink_parent_cannot_store_credentials(self):
        self.path.parent.chmod(0o750)
        with self.assertRaises(module.CredentialError): module.store(self.value, self.path)
        self.path.parent.chmod(0o700)
        link = self.path.parent / 'parent-link'
        link.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(module.CredentialError): module.store(self.value, link / 'new.json')
        self.assertFalse(self.path.exists())

    def test_opaque_key_has_no_invented_prefix_but_whitespace_and_control_bytes_fail(self):
        for key in ['opaque.unknown-prefix_0123', 'a' * 2048]:
            self.assertEqual(module.validate({**self.value, 'api_key': key})['api_key'], key)
        for key in ['', 'a' * 2049, 'Bearer ' + self.key, 'x\ny', '\x00', 'é', None]:
            with self.subTest(key_type=type(key).__name__), self.assertRaises(module.CredentialError):
                module.validate({**self.value, 'api_key': key})
        for fields in [dict(endpoint='ws://app.vmhunter.com:2701'), dict(mode='enabled'),
                       dict(version=True), dict(extra='ignored')]:
            with self.assertRaises(module.CredentialError): module.validate({**self.value, **fields})

    def test_mismatched_masked_entry_never_creates_a_file(self):
        answers = iter([self.key, 'different'])
        with self.assertRaises(module.CredentialError):
            module.collect(lambda _label: next(answers))
        self.assertFalse(self.path.exists())

    def test_getpass_echo_fallback_is_a_failure_instead_of_exposing_the_key(self):
        def no_tty(_label):
            warnings.warn('synthetic terminal missing', getpass.GetPassWarning)
            raise AssertionError('must not reach echoing input')
        with self.assertRaises(getpass.GetPassWarning): module.collect(no_tty)

    def test_interrupted_serialization_removes_the_incomplete_secret(self):
        with patch.object(module.json, 'dump', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            module.store(self.value, self.path)
        self.assertFalse(self.path.exists())

    def test_bounded_reads_reject_malformed_files_without_disclosing_their_content(self):
        module.store(self.value, self.path)
        for raw in ['x' * 8193, self.key, json.dumps({**self.value, 'mode': self.key})]:
            self.path.write_text(raw)
            with self.assertRaises(module.CredentialError) as error: module.load(self.path)
            self.assertNotIn(self.key, str(error.exception))

    def test_non_root_cli_never_prompts_or_reads_a_secret(self):
        with patch.object(module.os, 'geteuid', return_value=10001), \
                patch.object(module, 'collect') as collect, \
                patch.object(module, 'load') as load, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(module.main([]), 1)
            self.assertEqual(module.main(['status']), 1)
            collect.assert_not_called()
            load.assert_not_called()

    def test_default_store_is_offline_and_status_never_reports_the_key(self):
        import socket
        import urllib.request
        output = io.StringIO()
        with patch.object(module, 'CONFIG', self.path), patch.object(module.os, 'geteuid', return_value=0), \
                patch.object(module, 'private_parent'), patch.object(module, 'collect', return_value=self.value), \
                patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')), \
                patch.object(urllib.request, 'urlopen', side_effect=AssertionError('network forbidden')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(module.main([]), 0)
            with patch.object(module, 'load', return_value=self.value):
                self.assertEqual(module.main(['status']), 0)
        self.assertEqual(module.load(self.path), self.value)
        self.assertNotIn(self.key, output.getvalue())
        self.assertIn('reste à vérifier', output.getvalue())

    def test_unexpected_errors_never_print_secret_values(self):
        error = io.StringIO()
        with patch.object(module.os, 'geteuid', return_value=0), patch.object(module, 'private_parent'), \
                patch.object(module, 'CONFIG', self.path), \
                patch.object(module, 'collect', side_effect=RuntimeError(self.key)), \
                contextlib.redirect_stderr(error):
            self.assertEqual(module.main([]), 1)
        self.assertNotIn(self.key, error.getvalue())
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()

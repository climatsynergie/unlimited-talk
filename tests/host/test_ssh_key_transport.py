import base64
import importlib.util
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('prepare_ssh_key', Path(__file__).resolve().parents[2] / 'scripts/prepare_ssh_key.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class SSHSecretTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        key = self.root / 'fixture'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
        self.key = key.read_text()
        self.fingerprint = subprocess.check_output(['ssh-keygen', '-lf', str(key) + '.pub'], text=True).split()[1]

    def tearDown(self):
        self.tmp.cleanup()

    def test_multiline_crlf_and_escaped_newlines_preserve_key_identity(self):
        for i, value in enumerate((self.key, self.key.replace('\n', '\r\n'), self.key.replace('\n', '\\n'))):
            path = self.root / ('prepared-' + str(i))
            self.assertEqual(transport.prepare(path, value), self.fingerprint)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_base64_transport_preserves_key_identity(self):
        encoded = base64.b64encode(self.key.encode()).decode()
        self.assertEqual(transport.prepare(self.root / 'encoded', encoded), self.fingerprint)

    def test_rejects_truncated_key_and_console_output_without_exposing_content(self):
        values = ('root@server:~# command\n' + self.key, self.key.replace(transport.END, ''),
                  self.key.replace(self.key.splitlines()[2], ''))
        for i, value in enumerate(values):
            path = self.root / ('invalid-' + str(i))
            with self.assertRaises(ValueError) as error:
                transport.prepare(path, value)
            self.assertNotIn(self.key.splitlines()[1], str(error.exception))
            self.assertFalse(path.exists())

    def test_refuses_existing_target(self):
        path = self.root / 'existing'
        path.write_text('keep')
        with self.assertRaises(FileExistsError):
            transport.prepare(path, self.key)
        self.assertEqual(path.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()

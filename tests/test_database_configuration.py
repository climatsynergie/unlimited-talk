import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.database import make_engine


class DatabaseConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        password = root / 'password'
        password.write_text('x' * 48)
        self.ca = root / 'ca.crt'
        self.ca.write_text('-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n')
        self.env = {'APP_ENV': 'staging', 'COMMUNICATIONS_MODE': 'disabled',
                    'DB_DEPLOYMENT': 'managed',
                    'DB_HOST': 'private-db-staging-example.d.db.ondigitalocean.com',
                    'DB_NAME': 'unlimited_talk_staging', 'DB_USER': 'ut_staging_runtime',
                    'DB_PASSWORD_FILE': str(password), 'DB_SSLMODE': 'verify-full',
                    'DB_SSLROOTCERT': str(self.ca)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_managed_configuration_enforces_tls_and_bounded_pool(self):
        with patch.dict(os.environ, self.env, clear=True):
            engine = make_engine()
            try:
                self.assertEqual(engine.url.port, 25060)
                self.assertEqual(engine.pool.size(), 2)
                _, args = engine.dialect.create_connect_args(engine.url)
                self.assertNotIn('password=', repr(engine.url))
            finally:
                engine.dispose()

    def test_invalid_targets_and_live_mode_fail_closed(self):
        for key, value in [('APP_ENV', 'production'), ('COMMUNICATIONS_MODE', 'live'),
                           ('DB_HOST', 'localhost'), ('DB_NAME', 'defaultdb'),
                           ('DB_USER', 'doadmin'), ('DB_SSLMODE', 'require'),
                           ('DB_DEPLOYMENT', 'unknown')]:
            with self.subTest(key=key), patch.dict(os.environ, {**self.env, key: value}, clear=True):
                with self.assertRaises(RuntimeError):
                    make_engine()

    def test_missing_ca_blocks_managed_connection(self):
        self.ca.unlink()
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(RuntimeError):
                make_engine()

    def test_local_development_still_supported(self):
        with patch.dict(os.environ, {**self.env, 'DB_DEPLOYMENT': 'local', 'DB_HOST': 'db'}, clear=True):
            engine = make_engine()
            self.assertEqual(engine.url.host, 'db')
            self.assertEqual(engine.url.port, 5432)
            engine.dispose()


if __name__ == '__main__':
    unittest.main()

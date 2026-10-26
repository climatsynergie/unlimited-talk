import base64
from datetime import datetime, timezone
import tempfile
from pathlib import Path
import unittest

from cryptography.fernet import Fernet, InvalidToken

from app.identity.security import (digest, email_address, encryption_key, hash_password,
                                   otp_counter, validate_origin, validate_password,
                                   verify_password)


class IdentitySecurityTests(unittest.TestCase):
    def test_twelve_character_boundary_for_all_password_entrypoints(self):
        from pydantic import ValidationError
        from app.identity.routes import Acceptance, PasswordChange, ResetPassword
        valid='AbCdEf1234!?'
        self.assertEqual(len(valid),12)
        self.assertEqual(validate_password(valid),valid)
        for invalid in [valid[:-1],valid+'x'*117]:
            with self.assertRaises(ValueError): validate_password(invalid)
        for model,extra in [(Acceptance,{'token':'x'*43}),
                            (ResetPassword,{'token':'x'*43})]:
            model(password=valid,**extra)
            with self.assertRaises(ValidationError): model(password=valid[:-1],**extra)
        PasswordChange(current_password='old',new_password=valid)
        with self.assertRaises(ValidationError): PasswordChange(current_password='old',new_password=valid[:-1])

    def test_password_salts_and_wrong_password(self):
        password = 'A unique passphrase for testing 2026!'
        a,b = hash_password(password),hash_password(password)
        self.assertNotEqual(a,b)
        self.assertTrue(a.startswith('$argon2id$'))
        self.assertTrue(verify_password(a,password))
        self.assertFalse(verify_password(a,'incorrect'))
        self.assertFalse(verify_password(None,'incorrect'))

    def test_password_policy_and_email_normalization(self):
        self.assertEqual(email_address('  User@Example.com '),'user@example.com')
        for candidate in ['not-an-email','a@b','user@a.com\nsecond@b.com']:
            with self.assertRaises(ValueError): email_address(candidate)
        for candidate in ['too short','x'*40,'passwordpassword']:
            with self.assertRaises(ValueError): validate_password(candidate)
        self.assertEqual(validate_password('Les phrases longues sont permises!'),'Les phrases longues sont permises!')

    def test_totp_rfc_vector_and_replay_rejection(self):
        secret = base64.b32encode(b'12345678901234567890').decode()
        now = datetime.fromtimestamp(59,timezone.utc)
        self.assertEqual(otp_counter(secret,'287082',-1,now),1)
        self.assertIsNone(otp_counter(secret,'287082',1,now))
        self.assertIsNone(otp_counter(secret,'nototp',-1,now))

    def test_encrypted_secrets_reject_wrong_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'key';path.write_bytes(Fernet.generate_key())
            cipher=encryption_key(path);encoded=cipher.encrypt(b'secret')
            self.assertNotIn(b'secret',encoded)
            self.assertEqual(cipher.decrypt(encoded),b'secret')
            with self.assertRaises(InvalidToken): Fernet(Fernet.generate_key()).decrypt(encoded)

    def test_managed_origin_requires_https(self):
        self.assertEqual(validate_origin('https://staging.example.com','managed'),'https://staging.example.com')
        for origin in ['http://staging.example.com','https://user:password@example.com','https://example.com/path','https://example.com?query']:
            with self.assertRaises(ValueError): validate_origin(origin,'managed')
        with self.assertRaises(ValueError): validate_origin('http://localhost:1234','local')

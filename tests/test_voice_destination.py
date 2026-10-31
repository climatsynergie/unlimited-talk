"""A typed number cannot silently fall back to a different recipient."""
from types import SimpleNamespace
import unittest
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from app.telephony.routes import Reservation
from app.telephony.service import validate_destination


class VoiceDestinationTests(unittest.TestCase):
    def setUp(self):
        self.profile = SimpleNamespace(approved_destination='+14165550101')

    def test_explicit_number_is_bound_to_the_controlled_destination(self):
        self.assertEqual(validate_destination('+14165550101', self.profile), '+14165550101')
        for value in ['', '+14165550109', '4165550101', '+14165550101\n', '+14165550101 ext 2', 'sip:test@example.invalid']:
            with self.subTest(value=value), self.assertRaises(HTTPException) as caught:
                validate_destination(value, self.profile)
            self.assertEqual(caught.exception.status_code, 400)
            self.assertNotIn(self.profile.approved_destination, caught.exception.detail)

    def test_only_omission_keeps_preceding_browser_compatibility(self):
        old = Reservation(id=uuid4())
        self.assertEqual(validate_destination(old.destination, self.profile), self.profile.approved_destination)
        for value in [None, True, 14165550101]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Reservation(id=uuid4(), destination=value)
        with self.assertRaises(ValidationError):
            Reservation(id=uuid4(), destination='+14165550101', To='+14165550109')

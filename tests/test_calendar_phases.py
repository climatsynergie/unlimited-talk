import unittest
from pydantic import ValidationError
from app.calendar.phases import LIFECYCLE, next_phase
from app.calendar.routes import Booking, Update

class CalendarPhaseTests(unittest.TestCase):
    schedule=dict(local_start='2030-11-20T14:00',timezone='America/Toronto',duration_minutes=30)
    def test_new_phases_keep_existing_lifecycle_policies(self):
        for phase,status in {'confirmed':'booked','sold':'completed','cancelled':'cancelled','invalid':'cancelled','non_compliant':'cancelled'}.items():
            with self.subTest(phase=phase):
                self.assertEqual(Update(version=0,status=status,phase=phase,**self.schedule).phase,phase)
    def test_inconsistent_phase_is_rejected(self):
        for phase,status in LIFECYCLE.items():
            with self.subTest(phase=phase):
                with self.assertRaises(ValidationError):Update(version=0,status='no_show' if status!='no_show' else 'booked',phase=phase,**self.schedule)
    def test_legacy_edit_retains_a_compatible_phase(self):
        self.assertEqual(next_phase('booked',previous='confirmed'),'confirmed')
        self.assertEqual(next_phase('cancelled',previous='confirmed'),'cancelled')
        self.assertEqual(next_phase('completed',previous='sold'),'sold')
    def test_source_followup_requires_paired_version(self):
        body=dict(id='00000000-0000-0000-0000-000000000001',campaign_id='00000000-0000-0000-0000-000000000002',contact_id='00000000-0000-0000-0000-000000000003',membership_version=0,**self.schedule)
        self.assertIsNone(Booking(**body).source_followup_id)
        for change in [{'source_followup_id':body['id']},{'source_followup_version':0}]:
            with self.assertRaises(ValidationError):Booking(**body,**change)

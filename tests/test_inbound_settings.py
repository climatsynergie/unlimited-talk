from datetime import datetime, timezone
from uuid import uuid4
import unittest
from pydantic import ValidationError
from app.telephony.inbound_settings import Settings, within_hours
from app.telephony.inbound_routes import Change


class InboundSettingsTests(unittest.TestCase):
    def test_normalized_settings_and_no_default_open_hours(self):
        q=Settings(name=' Équipe Montréal ',phone='+1 (514) 555-0100')
        self.assertEqual(q.phone,'+15145550100')
        self.assertEqual(q.name,'Équipe Montréal')
        self.assertEqual(q.hours,[])
        self.assertFalse(within_hours([],q.timezone,datetime.now(timezone.utc)))

    def test_ambiguous_settings_and_overlapping_hours_rejected(self):
        user=str(uuid4())
        for change in [dict(name='  '),dict(phone='+15145550100 ext2'),dict(phone='+15145550100\n'),
            dict(timezone='Invalid/Zone'),dict(max_wait_seconds=True),dict(offer_seconds=61),
            dict(max_wait_seconds=10,offer_seconds=20),dict(agents=[dict(user_id=user),dict(user_id=user)]),
            dict(hours=[dict(weekday=0,start=600,end=500)]),dict(hours=[dict(weekday=0,start=0,end=1440),dict(weekday=0,start=900,end=1000)])]:
            with self.subTest(change=change),self.assertRaises(ValidationError):
                Settings(**{**dict(name='Équipe',phone='+15145550100'),**change})

    def test_hours_are_local_half_open_and_respect_dst(self):
        hours=[dict(weekday=6,start=60,end=120)]
        # Both occurrences of 01:30 during Toronto's repeated autumn hour.
        for hour in [5,6]:
            self.assertTrue(within_hours(hours,'America/Toronto',datetime(2026,11,1,hour,30,tzinfo=timezone.utc)))
        self.assertFalse(within_hours(hours,'America/Toronto',datetime(2026,11,1,7,tzinfo=timezone.utc)))
        self.assertFalse(within_hours(hours,'America/Toronto',datetime(2026,11,2,6,30,tzinfo=timezone.utc)))
        with self.assertRaises(ValueError):within_hours(hours,'America/Toronto',datetime(2026,11,1))

    def test_callback_requires_real_schedule_and_pending_has_no_owner(self):
        base=dict(request_id=uuid4(),version=0)
        for change in [dict(stage='callback'),dict(stage='pending',owner_id=uuid4()),dict(stage='claimed',local_start='2030-01-01T12:00'),dict(stage='callback',local_start='2030-01-01T12:00+01:00',timezone='America/Toronto')]:
            with self.subTest(change=change),self.assertRaises(ValidationError):Change(**base,**change)

    def test_malformed_terminal_input_is_rejected_before_any_database_write(self):
        from app.telephony.inbound_service import record_missed
        now=datetime.now(timezone.utc)
        base=dict(queue_id=uuid4(),account_sid='AC'+'a'*32,call_sid='CA'+'b'*32,caller_number=None,called_number='+15145550100',outcome='missed',received_at=now,ended_at=now)
        for change in [dict(account_sid=None),dict(call_sid=True),dict(caller_number=15145550101),dict(called_number=None),dict(outcome='answered'),dict(received_at=datetime(2026,1,1))]:
            with self.subTest(change=change),self.assertRaises(ValueError):record_missed(None,**{**base,**change})

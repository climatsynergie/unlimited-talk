from datetime import datetime, timezone
import unittest
from fastapi import HTTPException
from app.calendar.timezones import possibilities, resolve


class CalendarTimezoneTests(unittest.TestCase):
    def test_spring_gap_does_not_invent_an_instant(self):
        local=datetime(2026,3,8,2,30)
        self.assertEqual(possibilities(local,'America/Toronto'),[])
        with self.assertRaises(HTTPException):resolve(local,'America/Toronto',None)

    def test_fall_overlap_requires_explicit_offset(self):
        local=datetime(2026,11,1,1,30)
        choices=possibilities(local,'America/Toronto')
        self.assertEqual([c['utc_offset_minutes'] for c in choices],[-240,-300])
        with self.assertRaises(HTTPException):resolve(local,'America/Toronto',None)
        self.assertEqual(resolve(local,'America/Toronto',-300),datetime(2026,11,1,6,30,tzinfo=timezone.utc))
        with self.assertRaises(HTTPException):resolve(local,'America/Toronto',0)

    def test_half_hour_zone_and_bad_zone(self):
        self.assertEqual(resolve(datetime(2026,1,1,12),'America/St_Johns',None),datetime(2026,1,1,15,30,tzinfo=timezone.utc))
        with self.assertRaises(HTTPException):possibilities(datetime(2026,1,1),'Canada/Invalid')

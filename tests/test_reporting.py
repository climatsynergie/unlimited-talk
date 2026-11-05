"""Reporting boundaries, truthful empty values and safe native Excel output."""
from datetime import date,datetime,timezone
from io import BytesIO
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile
from fastapi import HTTPException
from openpyxl import load_workbook
from app.reporting.service import Period,metrics
from app.reporting.excel import workbook

class ReportingTests(unittest.TestCase):
    def test_calendar_three_month_limit_and_invalid_inputs(self):
        self.assertEqual(Period(date(2026,1,31),date(2026,4,30),'America/Toronto').bounds()[0].day,31)
        for value in [Period(date(2026,1,31),date(2026,5,1),'UTC'),Period(date(2026,5,1),date(2026,4,1),'UTC'),
                      Period(date(9999,1,1),date(9999,2,1),'UTC'),Period(date(2026,1,1),date(2026,1,1),'../UTC')]:
            with self.subTest(value=value),self.assertRaises(HTTPException):value.bounds()

    def test_real_hours_survive_both_daylight_saving_boundaries(self):
        for day,expected in [(date(2026,3,8),23),(date(2026,11,1),25)]:
            start,end=Period(day,day,'America/Toronto').bounds()
            self.assertEqual((end-start).total_seconds()/3600,expected)

    def test_empty_activity_and_unknown_duration_are_not_false_rates(self):
        result=metrics()
        self.assertEqual(result['calls'],0)
        self.assertIsNone(result['answer_rate']);self.assertIsNone(result['average_talk_seconds'])
        result=metrics(dict(calls=10,answered=5,bookings=2,talk_seconds=120,duration_known=2,duration_missing=3))
        self.assertEqual(result['answer_rate'],50);self.assertEqual(result['average_talk_seconds'],60)
        self.assertEqual(result['bookings_per_100_calls'],20)

    def test_excel_has_typed_numbers_zero_days_and_no_user_formulas(self):
        identifier=uuid4();values=metrics(dict(calls=12,answered=6,talk_seconds=120,duration_known=2))
        report=dict(period=dict(start=date(2026,1,1),end=date(2026,1,2),timezone='America/Toronto'),generated_at=datetime.now(timezone.utc),
            agents=[dict(id=identifier,display_name='=HYPERLINK("https://untrusted.invalid","Agent")',email='agent@example.invalid',metrics=values)],
            daily=[dict(agent_id=str(identifier),date='2026-01-01',**values),dict(agent_id=str(identifier),date='2026-01-02',**metrics())],
            hourly=[dict(starts_at=datetime(2026,1,1,5,tzinfo=timezone.utc),date='2026-01-01',label='00:00',utc_offset='-0500',**values)],definitions={'calls':'Les réservations ne sont pas des appels.'})
        content=workbook(report)
        book=load_workbook(BytesIO(content),read_only=True,data_only=False)
        self.assertEqual(book.sheetnames,['Synthèse','Par jour','Par heure','Repères'])
        summary=list(book['Synthèse'].rows)
        self.assertEqual(summary[1][0].data_type,'s');self.assertTrue(summary[1][0].value.startswith('='))
        self.assertEqual(summary[1][2].value,12);self.assertEqual(summary[1][2].data_type,'n')
        daily=list(book['Par jour'].values);self.assertEqual(daily[2][3],0)
        with ZipFile(BytesIO(content)) as archive:
            for name in archive.namelist():
                if name.startswith('xl/worksheets/'):
                    self.assertNotIn(b'<f>',archive.read(name))

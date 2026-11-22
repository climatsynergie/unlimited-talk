import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from fastapi import HTTPException
from app.calendar import text_export as export


class CalendarTextExportTests(unittest.TestCase):
    def row(self, answers=None):
        return dict(starts_at=datetime(2026,11,20,0,tzinfo=timezone.utc),status='booked',phase='confirmed',
                    phone='+14388766496',profile={'display_name':'Client synthétique','address':'Ancienne adresse'},
                    creator_name='Agent QA',campaign_name='Campagne QA',notes='Notes enregistrées',
                    qualification={'schema_version':3,'answers':answers or {}})

    def test_french_date_local_time_and_utf8(self):
        result=export.render(date(2026,11,19),'America/Toronto',[self.row()])
        self.assertTrue(result.startswith(b'\xef\xbb\xbf'))
        text=result.decode('utf-8-sig')
        for value in ['jeudi 19 novembre 2026 à 19 h 00','Statut : Confirmé','Booker par : Agent QA','Client synthétique','Notes enregistrées']:
            self.assertIn(value,text)

    def test_saved_qualification_and_all_supplied_fields_without_inventing_answers(self):
        answers={key:'Réponse '+key for key,_ in export.FIELDS}
        answers.update(civic_number='1821',street='Rue fictive',city='Québec',postal_code='Texte libre',hydro_bill='330 $ par mois',construction_year='2019',comments='Décision dans une semaine\nou deux.')
        text=export.appointment_text(self.row(answers),'America/Toronto')
        for _,label in export.FIELDS:self.assertIn(label+' :',text)
        self.assertIn('1821 Rue fictive, Québec Texte libre',text)
        self.assertIn('2019',text);self.assertIn('Décision dans une semaine\nou deux.',text)
        self.assertNotIn('Ancienne adresse',text)
        self.assertNotIn('depuis 8 ans',text)

    def test_missing_qualification_and_contact_profile_fallback(self):
        row=self.row();row['qualification']=None
        row['profile']={'first_name':'Émilie','last_name':'QA','address':'10 Rue exemple','city':'Québec','province':'QC','postal_code':'G1A 1A1'}
        text=export.appointment_text(row,'America/Toronto')
        self.assertIn('Nom : Émilie QA',text)
        self.assertIn('Adresse : 10 Rue exemple, Québec QC G1A 1A1',text)
        self.assertIn('Qualification : non renseignée',text)
        self.assertNotIn('Thermopompe : Non',text)

    def test_iso_sql_json_and_dst_repeated_hour_are_unambiguous(self):
        a=self.row();a['starts_at']='2026-11-01T05:30:00+00:00'
        b=self.row();b['starts_at']='2026-11-01T06:30:00Z'
        self.assertIn('UTC-0400',export.appointment_text(a,'America/Toronto'))
        self.assertIn('UTC-0500',export.appointment_text(b,'America/Toronto'))

    def test_day_bounds_follow_23_and_25_hour_days(self):
        for day,hours in [(date(2026,3,8),23),(date(2026,11,1),25),(date(2026,11,19),24)]:
            start,end=export.day_bounds(day,'America/Toronto')
            self.assertEqual((end-start).total_seconds(),hours*3600)
        self.assertEqual(export.day_bounds(date(2026,11,19),'America/Toronto')[0].isoformat(),'2026-11-19T05:00:00+00:00')

    def test_invalid_zone_and_date_rejected(self):
        for day,zone in [(date(1999,1,1),'UTC'),(date(2101,1,1),'UTC'),(date(2026,1,1),'Bad/Zone'),(date(2026,1,1),'/etc/passwd')]:
            with self.assertRaises(HTTPException) as result:export.day_bounds(day,zone)
            self.assertEqual(result.exception.status_code,422)

    def test_export_size_failure_never_returns_a_partial_file(self):
        with patch.object(export,'MAX_BYTES',100):
            with self.assertRaises(HTTPException) as result:export.render(date(2026,11,19),'UTC',[self.row()])
        self.assertEqual(result.exception.status_code,422)

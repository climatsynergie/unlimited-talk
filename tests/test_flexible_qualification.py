"""User policy: optional, lossless qualification independent of booking completeness."""
import copy
import json
from pathlib import Path
import unittest
from pydantic import ValidationError
from app.calendar.routes import Booking, Update
from app.qualification import Qualification, SCHEMA, complete_snapshot

FIXTURE=json.loads(Path(__file__).with_name('qualification-fixture.json').read_text())
BASE=dict(id='00000000-0000-0000-0000-000000000001',campaign_id='00000000-0000-0000-0000-000000000002',
 contact_id='00000000-0000-0000-0000-000000000003',membership_version=0,
 local_start='2026-11-20T10:00',timezone='America/Toronto',duration_minutes=30)

class FlexibleQualificationTests(unittest.TestCase):
 def test_every_question_can_be_empty_for_a_booking(self):
  value=Booking.model_validate({**BASE,'qualification':{'schema_version':3,'answers':{}}})
  self.assertTrue(all(v=='' for v in complete_snapshot(value.qualification)['answers'].values()))
 def test_postal_text_is_saved_exactly_without_format_or_case_rules(self):
  for postal in ('','j2k4w2','H2X\u00a01Y4','90210','  H2O ? à confirmer  ','inconnu'):
   with self.subTest(postal=postal):
    value=Qualification(schema_version=3,answers={'postal_code':postal})
    self.assertEqual(complete_snapshot(value)['answers']['postal_code'],postal)
 def test_unlisted_answers_and_conditional_answers_are_not_erased(self):
  answers={'owner':'Non','owners':'Peut-être deux','heat_pump':'Non','heat_pump_age':'à vérifier','wall_pump_floors':'Étage inconnu','insulation':'Refaite en partie'}
  value=complete_snapshot(Qualification(schema_version=3,answers=answers))
  for key,entered in answers.items():self.assertEqual(value['answers'][key],entered)
 def test_whitespace_and_long_notes_are_retained(self):
  comment='  Client :\n'+('é\t'*3000)+'\n  '
  value=Qualification(schema_version=3,answers={'comments':comment})
  self.assertEqual(complete_snapshot(value)['answers']['comments'],comment)
 def test_missing_or_null_questionnaire_is_an_empty_booking_snapshot(self):
  for body in (BASE,{**BASE,'qualification':None}):
   self.assertEqual(Booking.model_validate(body).qualification.schema_version,3)
 def test_update_accepts_a_partial_snapshot(self):
  body={k:v for k,v in BASE.items() if k in ('local_start','timezone','duration_minutes')}
  value=Update.model_validate({**body,'version':0,'status':'booked','qualification':{'schema_version':3,'answers':{'postal_code':'abc'}}})
  self.assertEqual(complete_snapshot(value.qualification)['answers']['postal_code'],'abc')
 def test_schema_advertises_only_optional_questions(self):
  self.assertTrue(SCHEMA['fields'])
  self.assertTrue(all(not f['required'] and f['condition'] is None for f in SCHEMA['fields']))
 def test_unsupported_structure_and_nul_remain_safe(self):
  for body in ({'schema_version':4,'answers':{}},{'schema_version':3,'answers':{'unknown':'yes'}},{'schema_version':3,'answers':{'comments':{'nested':'value'}}},{'schema_version':3,'answers':{'comments':'bad\x00value'}}):
   with self.assertRaises((ValueError,ValidationError)):Qualification.model_validate(body)

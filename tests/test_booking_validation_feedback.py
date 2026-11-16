"""Booking failures must identify safe fields without echoing customer values."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.requests import Request
from app.calendar.routes import Booking
from app.campaigns.routes import QualificationSave
from app.main import validation_error
from app.qualification import Qualification,complete_snapshot

FIXTURE=json.loads(Path(__file__).with_name('qualification-fixture.json').read_text())
BODY=dict(id='00000000-0000-0000-0000-000000000001',campaign_id='00000000-0000-0000-0000-000000000002',
 contact_id='00000000-0000-0000-0000-000000000003',membership_version=0,qualification_revision=None,
 local_start='2026-11-20T14:00',timezone='America/Toronto',duration_minutes=30,qualification=FIXTURE)

def response(model,body,route='/api/calendar'):
 try:model.model_validate(body)
 except ValidationError as error:
  errors=error.errors()
  for entry in errors:entry['loc']=('body',*entry['loc'])
  request=Request({'type':'http','method':'POST','path':route,'headers':[], 'route':SimpleNamespace(path=route)})
  return json.loads(asyncio.run(validation_error(request,RequestValidationError(errors,body=body))).body)
 raise AssertionError('Expected rejected fixture')

class BookingValidationFeedbackTests(unittest.TestCase):
 def test_unsupported_text_names_the_field_and_keeps_the_entered_value_private(self):
  body=copy.deepcopy(BODY);body['qualification']['answers']['postal_code']='PRIVATE_INVALID_POSTAL\x00'
  value=response(Booking,body)
  self.assertIsInstance(value['detail'],str)
  self.assertIn('Code postal',value['detail'])
  self.assertNotIn('PRIVATE_INVALID_POSTAL',json.dumps(value))
 def test_draft_qualification_has_the_same_safe_text_feedback(self):
  qualification=copy.deepcopy(FIXTURE);qualification['answers']['postal_code']='PRIVATE_BAD_POSTAL\x00'
  value=response(QualificationSave,dict(request_id=BODY['id'],expected_revision=None,qualification=qualification),
   '/api/campaigns/{identifier}/contacts/{contact_id}/qualification')
  self.assertIn('Code postal',value['detail']);self.assertNotIn('PRIVATE_BAD_POSTAL',json.dumps(value))
 def test_missing_answer_is_accepted(self):
  body=copy.deepcopy(BODY);body['qualification']['answers'].pop('hydro_bill')
  self.assertEqual(complete_snapshot(Booking.model_validate(body).qualification)['answers']['hydro_bill'],'')
 def test_postal_presentations_are_retained_exactly_in_draft_and_booking(self):
  for value in ('h2x1y4','H2X 1Y4','H2X\u00a01Y4','H2X\u202f1Y4','H2X\t1Y4','H2X-1Y4'):
   with self.subTest(value=value):
    body=copy.deepcopy(BODY);body['qualification']['answers']['postal_code']=value
    self.assertEqual(complete_snapshot(Qualification.model_validate(body['qualification']))['answers']['postal_code'],value)
    self.assertEqual(Booking.model_validate(body).qualification.answers['postal_code'],value)
 def test_arbitrary_postal_text_is_accepted_without_guessing_a_correction(self):
  for value in ('90210','H2O 1Y4','H2X 1O4','H2X--1Y4','H2X/1Y4'):
   body=copy.deepcopy(BODY);body['qualification']['answers']['postal_code']=value
   self.assertEqual(Booking.model_validate(body).qualification.answers['postal_code'],value)
 def test_schedule_error_is_actionable_without_the_submitted_text(self):
  body=copy.deepcopy(BODY);body['local_start']='PRIVATE_DATE_VALUE'
  value=response(Booking,body);self.assertIn('Date',value['detail']);self.assertNotIn('PRIVATE_DATE_VALUE',json.dumps(value))
 def test_unknown_exception_context_and_authentication_errors_stay_redacted(self):
  errors=[dict(loc=('body','password'),type='value_error',msg='PRIVATE_PASSWORD',input='PRIVATE_PASSWORD',ctx={'error':ValueError('PRIVATE_PASSWORD')})]
  for route in ('/api/auth/password-reset','/api/calendar'):
   request=Request({'type':'http','method':'POST','path':route,'headers':[],'route':SimpleNamespace(path=route)})
   value=json.loads(asyncio.run(validation_error(request,RequestValidationError(errors))).body)
   self.assertNotIn('PRIVATE_PASSWORD',json.dumps(value))

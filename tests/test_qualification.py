"""Legacy questionnaire conditions and server-side booking requirements."""
import copy
import json
from pathlib import Path
import unittest
from pydantic import ValidationError
from app.qualification import FIELDS, Qualification, complete_snapshot, is_complete

FIXTURE = json.loads(Path(__file__).with_name('qualification-fixture.json').read_text())


class QualificationTests(unittest.TestCase):
    def test_complete_and_partial_snapshots(self):
        result = complete_snapshot(Qualification.model_validate(FIXTURE))
        self.assertTrue(is_complete(result))
        self.assertEqual(result['answers']['postal_code'], 'H2X 1Y4')
        self.assertFalse(is_complete(Qualification(schema_version=1, answers={'owner': 'Oui'}).model_dump()))

    def test_every_visible_required_question_is_enforced(self):
        for field in FIELDS:
            if not field['required'] or field['condition']:
                continue
            with self.subTest(field=field['key']):
                value = copy.deepcopy(FIXTURE)
                value['answers'].pop(field['key'])
                with self.assertRaisesRegex(ValueError, 'Champ obligatoire'):
                    complete_snapshot(Qualification.model_validate(value))

    def test_ownership_and_heat_pump_conditions(self):
        value = copy.deepcopy(FIXTURE)
        value['answers']['owner'] = 'Non'
        value['answers']['owners'] = '2 propriétaires'
        result = complete_snapshot(Qualification.model_validate(value))
        self.assertNotIn('owners', result['answers'])
        value['answers']['heat_pump'] = 'Oui, murale'
        with self.assertRaisesRegex(ValueError, 'Champ obligatoire'):
            complete_snapshot(Qualification.model_validate(value))
        value['answers'].update(wall_pump_floors='Oui, aux deux étages', heat_pump_age='5 ans')
        self.assertTrue(is_complete(complete_snapshot(Qualification.model_validate(value))))
        value['answers']['heat_pump'] = 'Oui, centrale'
        self.assertNotIn('wall_pump_floors', complete_snapshot(Qualification.model_validate(value))['answers'])
        value['answers']['heat_pump'] = 'Non'
        self.assertNotIn('heat_pump_age', complete_snapshot(Qualification.model_validate(value))['answers'])

    def test_normalization_happens_before_conditional_validation(self):
        value = copy.deepcopy(FIXTURE)
        value['answers'].update(owner=' Oui ', postal_code='h2x1y4')
        result = complete_snapshot(Qualification.model_validate(value))
        self.assertEqual(result['answers']['owners'], '2 propriétaires')
        self.assertEqual(result['answers']['postal_code'], 'H2X 1Y4')

    def test_invalid_or_unversioned_values_fail_closed(self):
        for patch in [{'schema_version': True}, {'schema_version': 3}, {'schema_version': '1'}, {'unexpected': 'value'},
                      {'answers': {'unknown': 'yes'}}, {'answers': {'owner': 'Maybe'}},
                      {'answers': {'heating_age': 12}}, {'answers': {'heating_age': 'a'*2001}},
                      {'answers': {'heating_age': 'bad\x00value'}}, {'answers': {'postal_code': '90210'}}]:
            with self.subTest(patch=patch), self.assertRaises((ValueError, ValidationError)):
                Qualification.model_validate({**FIXTURE, **patch})

    def test_new_visit_answers_are_saved_with_their_units_and_comments(self):
        result=complete_snapshot(Qualification.model_validate(FIXTURE))
        self.assertEqual(result['schema_version'],2)
        for key in ('owners_present','spouses_present','insulation','insulation_comment','hydro_bill'):
            self.assertEqual(result['answers'][key],FIXTURE['answers'][key])
        for key,bad in [('owners_present','Peut-être'),('spouses_present','Absent'),('insulation','Isolation récente')]:
            value=copy.deepcopy(FIXTURE);value['answers'][key]=bad
            with self.assertRaises(ValueError):Qualification.model_validate(value)

    def test_original_snapshots_keep_the_original_questionnaire_and_free_text(self):
        old=json.loads(Path(__file__).with_name('qualification-v1-fixture.json').read_text())
        original=copy.deepcopy(old)
        saved=complete_snapshot(Qualification.model_validate(old))
        self.assertTrue(is_complete(saved))
        self.assertEqual(saved['schema_version'],1)
        self.assertEqual(saved['answers']['insulation'],old['answers']['insulation'])
        self.assertNotIn('owners_present',saved['answers'])
        self.assertEqual(old,original)
        with self.assertRaises(ValueError):
            Qualification.model_validate({**old,'answers':{**old['answers'],'hydro_bill':'150 $ / mois'}})

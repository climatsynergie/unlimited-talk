"""Optional qualification policy and immutable legacy questionnaire snapshots."""
import copy
import json
from pathlib import Path
import unittest
from pydantic import ValidationError
from app.qualification import FIELDS, Qualification, complete_snapshot, is_complete

FIXTURE = json.loads(Path(__file__).with_name('qualification-fixture.json').read_text())


class QualificationTests(unittest.TestCase):
    def test_construction_year_is_optional_free_text_in_the_new_snapshot(self):
        value=copy.deepcopy(FIXTURE)
        value['schema_version']=3
        value['answers']['construction_year']='  Vers 1970 / inconnue exactement  '
        saved=complete_snapshot(Qualification.model_validate(value))
        self.assertEqual(saved['answers']['construction_year'],'  Vers 1970 / inconnue exactement  ')
        value['answers'].pop('construction_year')
        omitted=complete_snapshot(Qualification.model_validate(value))
        self.assertTrue(is_complete(omitted))
        self.assertEqual(omitted['answers']['construction_year'],'')
        value['answers']['construction_year']=1970
        with self.assertRaises(ValidationError):Qualification.model_validate(value)

    def test_complete_and_partial_snapshots(self):
        result = complete_snapshot(Qualification.model_validate(FIXTURE))
        self.assertTrue(is_complete(result))
        self.assertEqual(result['answers']['postal_code'], 'H2X 1Y4')
        self.assertTrue(is_complete(Qualification(schema_version=1, answers={'owner': 'Oui'}).model_dump()))

    def test_every_question_is_optional(self):
        for field in FIELDS:
            with self.subTest(field=field['key']):
                value = copy.deepcopy(FIXTURE)
                value['answers'].pop(field['key'],None)
                self.assertEqual(complete_snapshot(Qualification.model_validate(value))['answers'][field['key']], '')

    def test_conditional_answers_are_preserved_even_if_the_parent_choice_changes(self):
        value = copy.deepcopy(FIXTURE)
        value['answers'].update(owner='Non', owners='2 propriétaires', heat_pump='Non',
            wall_pump_floors='Oui, aux deux étages', heat_pump_age='5 ans')
        saved=complete_snapshot(Qualification.model_validate(value))
        for key in ('owners','wall_pump_floors','heat_pump_age'):
            self.assertEqual(saved['answers'][key],value['answers'][key])

    def test_original_spacing_case_and_postal_text_are_preserved(self):
        value = copy.deepcopy(FIXTURE)
        value['answers'].update(owner=' Oui ', postal_code='h2x1y4')
        result = complete_snapshot(Qualification.model_validate(value))
        self.assertEqual(result['answers']['owner'], ' Oui ')
        self.assertEqual(result['answers']['postal_code'], 'h2x1y4')

    def test_invalid_or_unversioned_values_fail_closed(self):
        for patch in [{'schema_version': True}, {'schema_version': 4}, {'schema_version': '1'}, {'unexpected': 'value'},
                      {'answers': {'unknown': 'yes'}},
                      {'answers': {'heating_age': 12}},
                      {'answers': {'heating_age': 'bad\x00value'}}]:
            with self.subTest(patch=patch), self.assertRaises((ValueError, ValidationError)):
                Qualification.model_validate({**FIXTURE, **patch})

    def test_new_visit_answers_are_saved_with_their_units_and_comments(self):
        result=complete_snapshot(Qualification.model_validate(FIXTURE))
        self.assertEqual(result['schema_version'],3)
        for key in ('owners_present','spouses_present','insulation','insulation_comment','hydro_bill'):
            self.assertEqual(result['answers'][key],FIXTURE['answers'][key])
        for key,bad in [('owners_present','Peut-être'),('spouses_present','Absent'),('insulation','Isolation récente')]:
            value=copy.deepcopy(FIXTURE);value['answers'][key]=bad
            self.assertEqual(Qualification.model_validate(value).answers[key],bad)

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

    def test_v2_snapshots_keep_their_fields_without_inventing_a_construction_year(self):
        old=json.loads(Path(__file__).with_name('qualification-v2-fixture.json').read_text())
        original=copy.deepcopy(old)
        saved=complete_snapshot(Qualification.model_validate(old))
        self.assertTrue(is_complete(saved))
        self.assertEqual(saved['schema_version'],2)
        self.assertNotIn('construction_year',saved['answers'])
        self.assertEqual(old,original)
        with self.assertRaises(ValueError):
            Qualification.model_validate({**old,'answers':{**old['answers'],'construction_year':'1970'}})

"""A stale disposition may only follow its owner's exact automatic call result."""
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
from fastapi import HTTPException
from app.campaigns import service


class Rows:
    def __init__(self,value):self.value=value
    def mappings(self):return self
    def first(self):return self.value


class CallContextTests(TestCase):
    def test_foreign_or_missing_call_context_never_authorizes_a_disposition(self):
        actor,campaign,contact,stage=[uuid4() for _ in range(4)]
        own=dict(actor_id=actor,campaign_id=campaign,contact_id=contact,membership_version=0,settled_membership_version=1,state='finished')
        variants=[None,{**own,'actor_id':uuid4()},{**own,'campaign_id':uuid4()},{**own,'contact_id':uuid4()}]
        for source in variants:
            with self.subTest(source=source):
                def query(db,sql,**values):
                    if 'voice_intents' in sql:return Rows(source)
                    if 'campaign_stages' in sql:return Rows(dict(kind='non_interested'))
                    return Rows(dict(id=contact))
                with patch.object(service,'replay',return_value=None),patch.object(service,'contact_access',return_value=dict(version=1)),patch.object(service,'query',side_effect=query):
                    with self.assertRaises(HTTPException) as caught:
                        service.move(None,dict(id=actor),campaign,contact,stage,0,uuid4(),uuid4())
                self.assertEqual(caught.exception.status_code,403)
                self.assertEqual(caught.exception.headers['X-Error-Code'],'call_context_mismatch')

    def test_human_changes_or_other_call_outcomes_cannot_be_rebased(self):
        actor,campaign,contact,stage=[uuid4() for _ in range(4)]
        own=dict(actor_id=actor,campaign_id=campaign,contact_id=contact,membership_version=0,settled_membership_version=1,state='finished')
        variants=[(own,2,'non_interested'),(own,1,'other'),({**own,'settled_membership_version':None},1,'non_interested'),({**own,'state':'active'},1,'non_interested'),({**own,'membership_version':1},2,'non_interested')]
        for source,current,kind in variants:
            with self.subTest(source=source,current=current,kind=kind):
                def query(db,sql,**values):
                    if 'voice_intents' in sql:return Rows(source)
                    if 'campaign_stages' in sql:return Rows(dict(kind=kind))
                    return Rows(dict(id=contact))
                with patch.object(service,'replay',return_value=None),patch.object(service,'contact_access',return_value=dict(version=current)),patch.object(service,'query',side_effect=query):
                    with self.assertRaises(HTTPException) as caught:
                        service.move(None,dict(id=actor),campaign,contact,stage,0,uuid4(),uuid4())
                self.assertEqual(caught.exception.status_code,409)
                self.assertEqual(caught.exception.headers['X-Error-Code'],'stale_campaign_contact')

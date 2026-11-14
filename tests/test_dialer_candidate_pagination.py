"""Raw rejected pages must advance; planner tuning belongs only to selection."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from app.telephony import dialer_service as dialer


class CandidatePaginationTests(unittest.TestCase):
    def row(self, position, eligible=False):
        return dict(campaign_id='campaign',contact_id=str(position),phone='+14165550100' if eligible else None,
                    candidate_order=position,candidate_key=str(position))

    def test_fully_rejected_pages_advance_and_never_hide_a_later_eligible_contact(self):
        pages=[[self.row(i) for i in range(1,101)], [self.row(i) for i in range(101,201)],
               [self.row(201),self.row(202,True)]]
        calls=[]
        def query(db,statement,**values):
            calls.append(values)
            return SimpleNamespace(mappings=lambda:SimpleNamespace(all=lambda:pages.pop(0)))
        with patch.object(dialer,'query',query):
            rows=list(dialer.candidates(object(),{'actor':'agent','admin':False,'account':'AC'},'campaign'))
        self.assertEqual([row['candidate_order'] for row in rows],[202])
        self.assertEqual([call['after'] for call in calls],[None,100,200])
        self.assertEqual([call['after_id'] for call in calls],[None,'100','200'])

    def test_callback_raw_pages_keep_due_priority_after_rejected_callback_page(self):
        pages=[[self.row(i) for i in range(1,101)],[self.row(101,True)]]
        cursors=[]
        def query(db,statement,**values):
            cursors.append((values['campaign'],values['after']))
            return SimpleNamespace(mappings=lambda:SimpleNamespace(all=lambda:pages.pop(0)))
        with patch.object(dialer,'query',query):
            rows=list(dialer.candidates(object(),{'actor':'agent','admin':False,'account':'AC'}))
        self.assertEqual([row['candidate_order'] for row in rows],[101])
        self.assertEqual(cursors,[(None,None),(None,100)])

    def test_next_selection_uses_transaction_local_jit_before_callback_then_campaign_streams(self):
        actor={'id':uuid4(),'session_hash':'a'*64,'role':'agent'};browser=uuid4();campaign=uuid4()
        row=dict(mode='running',browser_id=browser,session_hash=actor['session_hash'],generation=2,
                 campaign_id=campaign,lease_alive=True,hold_token=None)
        events=[]
        def query(db,statement,**values):
            events.append(statement)
            return SimpleNamespace(first=lambda:None,mappings=lambda:SimpleNamespace(first=lambda:None))
        def candidates(db,values,campaign_id=None):
            events.append(('candidate',campaign_id));return []
        with patch.object(dialer.completion,'settle_actor'),patch.object(dialer,'get',return_value=row),\
             patch.object(dialer,'query',query),patch.object(dialer,'candidates',candidates),\
             patch('app.telephony.incoming_schema.occupancy',return_value={'actor_busy':False}):
            result=dialer.next_call(object(),actor,SimpleNamespace(account_sid='AC'),browser,2,uuid4())
        self.assertEqual(result['idle'],'empty')
        self.assertEqual(events.count('SET LOCAL jit=off'),1)
        index=events.index('SET LOCAL jit=off')
        self.assertEqual(events[index+1:],[('candidate',None),('candidate',campaign)])
        self.assertEqual(result['dialer']['mode'],'running')

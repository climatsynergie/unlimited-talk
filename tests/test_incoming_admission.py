"""Admission closure must stop new media without discarding admitted callbacks."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID
from xml.etree import ElementTree
import unittest
from fastapi import HTTPException
from app.telephony import incoming_hooks as hooks, incoming_runtime as runtime, service
from app.telephony.twilio_voice import ManualVoiceProfile

class Result:
    def __init__(self,row=None):self.row=row
    def mappings(self):return self
    def first(self):return self.row
    def one(self):return self.row

class IncomingAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.profile=ManualVoiceProfile('AC'+'a'*32,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
            'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100')
        self.params=dict(CallSid='CA'+'1'*32,From='+14165550101',To=self.profile.caller_number,Direction='inbound')
        self.db=object();self.request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            engine=SimpleNamespace(begin=lambda:nullcontext(self.db)),voice_calling_enabled=False)))
        self.queries=[];self.existing=None
    def query(self,db,sql,**values):
        self.assertIs(db,self.db);self.queries.append(sql)
        if 'FROM staging.inbound_lines' in sql:return Result(dict(queue_id=UUID(int=1)))
        if 'FROM staging.inbound_calls' in sql:return Result(self.existing)
        if 'INSERT INTO staging.inbound_calls' in sql:
            return Result(dict(id=values['id'],state='waiting'))
        return Result()
    def initial(self):
        with patch.object(hooks,'installed',return_value=True),patch.object(runtime,'query',self.query):
            return hooks.apply(self.request,self.profile,'incoming',None,self.params)
    def existing_call(self):
        return dict(id=UUID(int=2),state='waiting',caller_fingerprint=service.fingerprint(dict(
            account=self.profile.account_sid,parent=self.params['CallSid'],caller=self.params['From'],called=self.params['To'])))
    def test_closed_admission_refuses_a_new_call_before_persistence_or_answer(self):
        decision=self.initial()
        self.assertEqual(decision['action'],'reject')
        self.assertFalse(any('INSERT INTO staging.inbound_calls' in sql for sql in self.queries))
        twiml=ElementTree.fromstring(hooks.render(self.profile,decision))
        self.assertEqual(twiml.find('Reject').attrib,{'reason':'busy'})
        self.assertIsNone(twiml.find('Say'));self.assertIsNone(twiml.find('Record'));self.assertIsNone(twiml.find('Dial'))
    def test_open_admission_still_persists_before_initial_twiml(self):
        self.request.app.state.voice_calling_enabled=True
        self.assertEqual(self.initial()['action'],'initial')
        self.assertEqual(sum('INSERT INTO staging.inbound_calls' in sql for sql in self.queries),1)
    def test_closed_admission_preserves_already_admitted_request_replays(self):
        self.existing=self.existing_call()
        self.assertEqual(self.initial()['call']['id'],self.existing['id'])
        self.assertFalse(any('INSERT INTO staging.inbound_calls' in sql for sql in self.queries))
    def test_closed_replay_does_not_skip_identity_binding(self):
        self.existing=self.existing_call();self.params['From']='+14165550102'
        with self.assertRaises(HTTPException) as caught:self.initial()
        self.assertEqual(caught.exception.status_code,403)
    def test_terminal_recovery_can_still_create_a_missing_ledger_entry(self):
        # parent_status calls receive(verified_voice=False) and finishes the row
        # inside the same transaction; it must not be mistaken for new media.
        with patch.object(runtime,'query',self.query):
            row=runtime.receive(self.db,self.profile,self.params,verified_voice=False)
        self.assertEqual(row['state'],'waiting')
        self.assertTrue(any('INSERT INTO staging.inbound_calls' in sql for sql in self.queries))
        self.assertFalse(any("route_state='active'" in sql for sql in self.queries))
    def test_admission_closure_still_processes_status_and_recording_callbacks(self):
        for kind,function in [('incoming-parent-status','parent_status'),('incoming-agent-status','child_status'),('incoming-recording','recording')]:
            with self.subTest(kind=kind),patch.object(hooks,'installed',return_value=True),patch.object(hooks.state,function) as callback:
                decision=hooks.apply(self.request,self.profile,kind,UUID(int=2),self.params)
                self.assertEqual(decision['action'],'hangup');callback.assert_called_once()

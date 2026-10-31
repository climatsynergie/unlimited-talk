"""GET-only recovery boundaries with synthetic provider identities, no network."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.parse import parse_qs, urlsplit
import urllib.error
from uuid import UUID

from app.telephony import service
from app.telephony.reconciliation import (PendingCall, Observation, ReadOnlyCalls, ProviderReadError,
                                          NoRedirect, MAX_RESPONSE_BYTES, reconcile_once)
from app.telephony.twilio_voice import ControlledVoiceProfile, client_identity


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.profile=ControlledVoiceProfile('AC'+'a'*32,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
            'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100','+14165550101')
        self.pending=PendingCall(UUID(int=1),UUID(int=2),service.profile_hash(self.profile),self.profile.account_sid,
            self.profile.caller_number,self.profile.approved_destination,'CA'+'1'*32,None)
        self.child=dict(account_sid=self.profile.account_sid,sid='CA'+'2'*32,parent_call_sid=self.pending.parent_call_sid,
                        direction='outbound-dial',**{'from':self.profile.caller_number,'to':self.profile.approved_destination},status='completed')
        self.parent=dict(account_sid=self.profile.account_sid,sid=self.pending.parent_call_sid,parent_call_sid=None,
                         **{'from':'client:'+client_identity(self.pending.actor_id,self.pending.id)},status='completed')
        self.calls=[]
        self.children=[self.child]
        self.extra={}

    def send(self,request):
        self.calls.append(request)
        self.assertEqual(request.method,'GET')
        self.assertIsNone(request.data)
        self.assertEqual(urlsplit(request.full_url).hostname,'api.twilio.com')
        if request.full_url.endswith('/Calls/'+self.parent['sid']+'.json'):return dict(self.parent)
        if request.full_url.endswith('/Calls/'+self.child['sid']+'.json'):return dict(self.child)
        self.assertTrue(request.full_url.split('?')[0].endswith('/Calls.json'))
        self.assertEqual(parse_qs(urlsplit(request.full_url).query),{'ParentCallSid':[self.pending.parent_call_sid],'PageSize':['2']})
        return dict(calls=self.children,next_page_uri=None,**self.extra)

    def read(self,pending=None):
        return ReadOnlyCalls(self.profile,self.send).read(pending or self.pending)

    def test_only_scoped_gets_and_relationships_can_prove_terminal_result(self):
        observed=self.read()
        self.assertTrue(observed.terminal)
        self.assertEqual(observed.child_call_sid,self.child['sid'])
        self.assertEqual(len(self.calls),3)
        self.assertTrue(self.calls[-1].full_url.endswith('/Calls/'+self.parent['sid']+'.json'))
        for obj in [self.pending,observed,self.profile,ReadOnlyCalls(self.profile)]:
            for value in [self.profile.api_key_secret,self.profile.shared_key_secret,self.profile.approved_destination]:
                self.assertNotIn(value,repr(obj))

    def test_parent_or_child_still_active_cannot_release_reservation(self):
        for parent,child in [('in-progress','completed'),('completed','in-progress'),('ringing','ringing')]:
            self.parent['status']=parent;self.child['status']=child
            self.assertFalse(self.read().terminal)

    def test_missing_child_list_does_not_omit_an_already_bound_child(self):
        self.children=[]
        observed=self.read(replace(self.pending,child_call_sid=self.child['sid']))
        self.assertEqual(observed.child_call_sid,self.child['sid'])
        self.assertEqual(len(self.calls),3)
        self.child['status']='in-progress'
        self.assertFalse(self.read(replace(self.pending,child_call_sid=self.child['sid'])).terminal)
        self.assertIsNone(self.read().child_call_sid)

    def test_incomplete_or_ambiguous_child_list_is_never_followed(self):
        self.children=[self.child,self.child]
        with self.assertRaises(ProviderReadError):self.read()
        self.children=[self.child]
        for value in ['https://untrusted.example/steal',{},'next-page']:
            def send(request):return {'calls':self.children,'next_page_uri':value}
            with self.subTest(value=value),self.assertRaises(ProviderReadError):
                ReadOnlyCalls(self.profile,send).read(self.pending)

    def test_foreign_ownership_client_target_direction_and_ids_are_rejected(self):
        for fields in [dict(account_sid='AC'+'9'*32),dict(parent_call_sid='CA'+'3'*32),
                       {'from':'+14165550109'},{'to':'+14165550109'},dict(direction='outbound-api'),
                       dict(status='unknown'),dict(status=[]),dict(sid='https://untrusted.example/call')]:
            original=self.child;self.child={**original,**fields};self.children=[self.child]
            with self.subTest(fields=list(fields)),self.assertRaises(ProviderReadError):self.read()
            self.child=original;self.children=[original]
        for fields in [dict(account_sid='AC'+'9'*32),dict(parent_call_sid='CA'+'3'*32),
                       {'from':'client:foreign'},dict(status='unknown')]:
            original=self.parent;self.parent={**original,**fields}
            with self.subTest(fields=list(fields)),self.assertRaises(ProviderReadError):self.read()
            self.parent=original

    def test_invalid_snapshot_and_unapproved_paths_cannot_send_any_request(self):
        for changes in [dict(account_sid='AC'+'9'*32),dict(destination='+14165550109'),
                        dict(profile_hash='wrong'),dict(parent_call_sid='../Calls'),dict(id='not-a-uuid')]:
            with self.subTest(changes=changes),self.assertRaises(ProviderReadError):self.read(replace(self.pending,**changes))
        self.assertEqual(self.calls,[])
        client=ReadOnlyCalls(self.profile,self.send)
        for path in ['/Calls.json','/Calls.json?To=anything','https://untrusted.example',
                     '/Calls/'+self.parent['sid']+'.json?query=1','/Calls/../Accounts.json']:
            with self.assertRaises(ProviderReadError):client._get(path)
        self.assertEqual(self.calls,[])

    def test_http_errors_and_unknown_exceptions_never_expose_provider_body_or_secret(self):
        for code in [401,403,404,429,500]:
            def send(request):raise urllib.error.HTTPError(request.full_url,code,self.profile.api_key_secret,{},None)
            with self.subTest(code=code),self.assertRaises(ProviderReadError) as error:
                ReadOnlyCalls(self.profile,send).read(self.pending)
            self.assertNotIn(self.profile.api_key_secret,str(error.exception))
        with self.assertRaises(ProviderReadError) as error:
            ReadOnlyCalls(self.profile,lambda request:(_ for _ in ()).throw(RuntimeError(self.profile.api_key_secret))).read(self.pending)
        self.assertEqual(str(error.exception),'provider_unavailable')

    def test_redirects_and_oversized_real_transport_responses_are_rejected(self):
        with self.assertRaises(ProviderReadError):
            NoRedirect().redirect_request(None,None,302,'Found',{},'https://untrusted.example')
        response=MagicMock();response.status=200;response.read.return_value=b'x'*(MAX_RESPONSE_BYTES+1)
        opener=MagicMock();opener.open.return_value.__enter__.return_value=response
        with patch('urllib.request.build_opener',return_value=opener),self.assertRaises(ProviderReadError):
            ReadOnlyCalls(self.profile).read(self.pending)
        self.assertEqual(opener.open.call_args.kwargs,{'timeout':5})

    def test_disabled_reconciliation_never_accesses_database_or_provider(self):
        engine=MagicMock();provider=MagicMock()
        result=reconcile_once(engine,None,provider)
        self.assertEqual(result['checked'],0)
        engine.connect.assert_not_called();provider.read.assert_not_called()

    def test_private_gateway_uses_only_its_bearer_and_cannot_target_another_origin(self):
        requests=[]
        def send(request):
            requests.append(request)
            if '/Calls.json?' in request.full_url:return {'calls':[],'meta':{},'next_page_uri':None}
            return self.parent
        client=ReadOnlyCalls(self.profile,send,gateway='http://172.30.8.1:8112',token='a'*64)
        self.assertTrue(client.read(self.pending).terminal)
        for request in requests:
            self.assertEqual(urlsplit(request.full_url).netloc,'172.30.8.1:8112')
            self.assertEqual(request.get_header('Authorization'),'Bearer '+'a'*64)
            self.assertNotIn(self.profile.api_key_secret,json.dumps(dict(request.headers)))
        for gateway,token in [('https://untrusted.example','a'*64),('http://172.30.8.1:8112','invalid')]:
            with self.assertRaises(ProviderReadError):ReadOnlyCalls(self.profile,gateway=gateway,token=token)


if __name__=='__main__':unittest.main()

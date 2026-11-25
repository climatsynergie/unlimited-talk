"""Real loopback HTTP verifies exact Twilio Media Stream request contracts."""
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.telephony import vmhunter as vm
from app.telephony.vmhunter_observer import Streams
from test_vmhunter import PROFILE


class StreamHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests=[];self.status=None;self.redirect=None;self.create_status=201;self.create_override=None;self.call_override=None
        self.call='CA'+'1'*32;self.stream='MZ'+'2'*32
        self.name='ut-vm-'+'a'*32
        async def handle(request):
            data=dict(await request.post())
            self.requests.append((request.method,request.path,data,request.headers.get('Authorization'),dict(request.query)))
            if self.redirect:return web.Response(status=302,headers={'Location':self.redirect})
            if self.status:return web.json_response({'private':'must not be reported'},status=self.status)
            if request.method=='GET':
                if request.path=='/Calls/'+self.call+'.json' and self.call_override is not None:
                    return web.json_response(self.call_override)
                return web.json_response({'code':20004},status=405)
            if 'Status' in data:
                return web.json_response({'sid':self.stream,'call_sid':self.call,'name':self.name,'status':data['Status']})
            return web.json_response(self.create_override if self.create_override is not None else {'sid':self.stream,'call_sid':self.call},status=self.create_status)
        app=web.Application();app.router.add_route('*','/{path:.*}',handle)
        self.server=TestServer(app);await self.server.start_server()
        self.session=aiohttp.ClientSession(trust_env=False)
        self.client=Streams(PROFILE,self.session)
        self.url_patch=patch.object(self.client,'url',side_effect=lambda call,stream=None:
            str(self.server.make_url('/Calls/'+call+'/Streams'+('/'+stream if stream else '')+'.json')))
        self.url_patch.start()

    async def asyncTearDown(self):
        self.url_patch.stop();await self.session.close();await self.server.close()

    async def test_create_uses_callee_inbound_track_and_no_call_control_fields(self):
        result=await self.client.start({'call_sid':self.call},'unique-test','SYNTHETIC-CAPABILITY')
        self.assertEqual(result,self.stream)
        method,path,data,auth,_=self.requests[0]
        self.assertEqual(method,'POST')
        self.assertEqual(path,'/Calls/'+self.call+'/Streams.json')
        self.assertEqual(data,{'Url':'wss://voice.example.invalid/api/telephony/vmhunter/media',
            'Track':'inbound_track','Name':'unique-test','Parameter1.Name':'ticket','Parameter1.Value':'SYNTHETIC-CAPABILITY'})
        self.assertEqual(auth,aiohttp.BasicAuth(PROFILE.api_key_sid,PROFILE.api_key_secret).encode())
        self.assertNotIn('Twiml',data);self.assertNotIn('To',data)

    async def test_stop_updates_only_the_stream_not_the_call(self):
        self.assertTrue(await self.client.stop(self.call,self.stream))
        self.assertEqual(self.requests[0][:3],('POST','/Calls/'+self.call+'/Streams/'+self.stream+'.json',{'Status':'stopped'}))

    async def test_real_provider_success_http_200_keeps_bound_stream_checks(self):
        self.create_status=200
        self.assertEqual(await self.client.start({'call_sid':self.call},self.name,'SYNTHETIC-CAPABILITY'),self.stream)
        for invalid in ({'sid':self.stream,'call_sid':'CA'+'3'*32},{'sid':'invalid','call_sid':self.call},{}):
            self.create_override=invalid
            with self.assertRaises(vm.ProtocolError):
                await self.client.start({'call_sid':self.call},self.name,'SYNTHETIC-CAPABILITY')

    async def test_timeout_recovery_stops_exact_named_stream_using_supported_post(self):
        self.assertEqual(await self.client.recover(self.call,self.name),self.stream)
        self.assertEqual(self.requests[0][:3],('POST','/Calls/'+self.call+'/Streams/'+self.name+'.json',{'Status':'stopped'}))
        self.assertNotIn('To',self.requests[0][2])
        self.assertFalse(any(request[0]=='GET' for request in self.requests))

    async def test_ambiguous_creation_missing_named_stream_does_not_clear_the_circuit(self):
        self.status=404
        self.assertIsNone(await self.client.recover(self.call,self.name))

    async def test_rejection_is_diagnostic_without_exposing_provider_body(self):
        self.status=400
        with self.assertLogs('app.telephony.vmhunter_observer',level='WARNING') as messages:
            with self.assertRaises(vm.ProtocolError):
                await self.client.start({'call_sid':self.call},self.name,'SYNTHETIC-CAPABILITY')
        self.assertIn('http_status=400',' '.join(messages.output))
        self.assertNotIn('private',' '.join(messages.output))
        self.assertNotIn('SYNTHETIC-CAPABILITY',' '.join(messages.output))

    async def test_auth_failure_never_returns_provider_body(self):
        self.status=401
        with self.assertRaises(vm.ProtocolError) as error:
            await self.client.start({'call_sid':self.call},'unique-test','SYNTHETIC-CAPABILITY')
        self.assertNotIn('private',str(error.exception))
        self.assertFalse(await self.client.stop(self.call,self.stream))

    async def test_redirects_never_forward_credentials_or_capability(self):
        self.redirect=str(self.server.make_url('/credential-stealer'))
        with self.assertRaises(vm.ProtocolError):
            await self.client.start({'call_sid':self.call},'unique-test','SYNTHETIC-CAPABILITY')
        self.assertEqual(len(self.requests),1)

    async def test_terminal_call_proof_requires_exact_account_sid_and_known_final_state(self):
        valid=dict(sid=self.call,account_sid=PROFILE.account_sid,status='completed')
        for status in ('completed','busy','no-answer','failed','canceled'):
            self.call_override=valid | {'status':status}
            self.assertTrue(await self.client.call_finished(self.call))
        for change in ({'status':'in-progress'},{'status':'ringing'},{'status':'queued'},
                {'status':'future'},{'status':[]},{'sid':'CA'+'3'*32},
                {'account_sid':'AC'+'4'*32}):
            self.call_override=valid | change
            self.assertFalse(await self.client.call_finished(self.call))
        self.call_override={}
        self.assertFalse(await self.client.call_finished(self.call))
        self.assertTrue(all(r[0]=='GET' and r[1]=='/Calls/'+self.call+'.json'
                            and r[2]=={} and r[4]=={} for r in self.requests))
        self.assertTrue(all(r[3]==aiohttp.BasicAuth(PROFILE.api_key_sid,PROFILE.api_key_secret).encode()
                            for r in self.requests))

    async def test_terminal_read_never_trusts_error_missing_resource_or_redirect(self):
        self.call_override=dict(sid=self.call,account_sid=PROFILE.account_sid,status='completed')
        for status in (400,401,403,404,500):
            self.status=status
            self.assertFalse(await self.client.call_finished(self.call))
        self.status=None;self.redirect=str(self.server.make_url('/credential-stealer'))
        self.assertFalse(await self.client.call_finished(self.call))
        self.assertEqual(len(self.requests),6)
        self.assertFalse(any(r[1]=='/credential-stealer' for r in self.requests))

    async def test_completed_call_with_already_removed_stream_is_safe(self):
        self.status=404
        self.assertTrue(await self.client.stop(self.call,self.stream))


if __name__=='__main__':unittest.main()

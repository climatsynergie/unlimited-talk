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
        self.requests=[];self.status=None;self.redirect=None
        self.call='CA'+'1'*32;self.stream='MZ'+'2'*32
        async def handle(request):
            data=dict(await request.post())
            self.requests.append((request.method,request.path,data,request.headers.get('Authorization'),dict(request.query)))
            if self.redirect:return web.Response(status=302,headers={'Location':self.redirect})
            if self.status:return web.json_response({'private':'must not be reported'},status=self.status)
            if request.method=='GET':
                return web.json_response({'streams':[{'sid':self.stream,'call_sid':self.call,'name':'unique-test'}]})
            if 'Status' in data:
                return web.json_response({'sid':self.stream,'status':data['Status']})
            return web.json_response({'sid':self.stream,'call_sid':self.call},status=201)
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

    async def test_timeout_recovery_is_read_only_and_uses_exact_stream_name(self):
        self.assertEqual(await self.client.recover(self.call,'unique-test'),self.stream)
        self.assertEqual(self.requests[0][0],'GET')
        self.assertEqual(self.requests[0][-1],{'PageSize':'4'})
        self.assertIsNone(await self.client.recover(self.call,'another-name'))

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

    async def test_completed_call_with_already_removed_stream_is_safe(self):
        self.status=404
        self.assertTrue(await self.client.stop(self.call,self.stream))


if __name__=='__main__':unittest.main()

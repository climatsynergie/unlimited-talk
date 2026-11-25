"""Execute HTTP admission, Twilio WebSocket and VM WebSocket on local loopback."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.telephony import vmhunter as vm
from app.telephony import vmhunter_observer as module
from test_vmhunter import PROFILE, policy, start, media


class Store:
    def __init__(self): self.claims=[];self.results=[]
    def claim(self,payload):
        if self.claims:return None
        result=payload | {'nonce':uuid4().hex}
        self.claims.append(result);return result
    def result(self,payload,result,**details):self.results.append((payload,result,details))


class Streams:
    def __init__(self):
        self.stopped=[];self.token=None;self.recovered=[]
        self.started=asyncio.Event();self.fail=False;self.stop_ok=True
    async def start(self,payload,name,token):
        self.token=token;self.started.set()
        if self.fail:raise TimeoutError()
        return 'MZ'+'c'*32
    async def recover(self,call,name):
        self.recovered.append((call,name));return 'MZ'+'c'*32
    async def stop(self,call,stream):self.stopped.append((call,stream));return self.stop_ok


class ObserverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received=[]
        self.answer={'AMDSTATUS':'MACHINE','AMDCAUSE':'MACHINE_BEEP'}
        async def provider(request):
            ws=web.WebSocketResponse();await ws.prepare(request)
            self.received.append(await ws.receive_json())
            try:
                message=await ws.receive()
                self.received.append(message.data)
                if message.type==aiohttp.WSMsgType.BINARY:
                    await ws.send_json(self.answer)
            finally:await ws.close()
            return ws
        provider_app=web.Application();provider_app.router.add_get('/ws',provider)
        self.upstream=TestServer(provider_app);await self.upstream.start_server()
        self.session=aiohttp.ClientSession(trust_env=False)
        self.store=Store();self.streams=Streams()
        self.pilot=vm.Pilot.parse(policy(enabled=True,agent_ids=[str(uuid4())],audio_approved=True,
                                        test_numbers=['+14165550101']))
        self.provider=vm.Client('SYNTHETIC-VM-KEY',session=self.session,
            endpoint=str(self.upstream.make_url('/ws')).replace('http:','ws:'))
        self.observer=module.Observer(PROFILE,self.pilot,self.store,self.streams,self.provider,
                                      job_seconds=0.5,handshake_seconds=0.05)
        self.server=TestServer(module.application(self.observer));await self.server.start_server()
        self.payload=dict(intent_id=str(uuid4()),call_sid='CA'+'b'*32,pilot_id=str(self.pilot.identifier))

    async def asyncTearDown(self):
        await self.server.close();await self.session.close();await self.upstream.close()

    async def dispatch(self,token=None):
        token=token or vm.ticket(PROFILE.shared_key_secret,'dispatch',self.payload)
        async with self.session.post(self.server.make_url('/private/observe'),json={'ticket':token}) as response:
            return response.status

    async def finish(self):
        for _ in range(300):
            if self.store.results:return self.store.results[-1]
            await asyncio.sleep(0.005)
        self.fail('observer did not complete')

    async def twilio(self,token=None,**changes):
        ws=await self.session.ws_connect(self.server.make_url(module.MEDIA_PATH))
        await ws.send_json({'event':'connected','protocol':'Call','version':'1.0.0'})
        await ws.send_json(start(customParameters={'ticket':token or self.streams.token},**changes))
        return ws

    async def test_full_synthetic_http_websocket_pipeline_without_hangup_or_crm_change(self):
        self.assertEqual(await self.dispatch(),202)
        await asyncio.wait_for(self.streams.started.wait(),1)
        async with await self.twilio() as ws:
            await ws.send_json(media())
            await ws.receive()
        _,result,details=await self.finish()
        self.assertEqual(result,vm.Result('MACHINE','MACHINE_BEEP'))
        self.assertEqual(result.observation_action,'continue')
        self.assertEqual(self.received[1],b'\0'*320)
        self.assertEqual(details,{'stop_confirmed':True})
        self.assertEqual(len(self.streams.stopped),1)
        self.assertNotIn('SYNTHETIC-VM-KEY',repr(self.store.results))

    async def test_invalid_expired_and_wrong_purpose_tickets_cannot_start_analysis(self):
        for token in ['wrong',vm.ticket('wrong-key','dispatch',self.payload),
                      vm.ticket(PROFILE.shared_key_secret,'media',self.payload),
                      vm.ticket(PROFILE.shared_key_secret,'dispatch',self.payload,now=1)]:
            self.assertEqual(await self.dispatch(token),403)
        self.assertFalse(self.store.claims);self.assertFalse(self.received)

    async def test_untrusted_stream_cannot_send_any_audio_to_provider(self):
        async with await self.twilio(token='invalid') as ws:
            message=await ws.receive()
            self.assertIn(message.type,{aiohttp.WSMsgType.CLOSE,aiohttp.WSMsgType.CLOSED})
        self.assertFalse(self.received)
        self.assertFalse(self.store.results)

    async def test_slow_handshake_is_bounded_and_does_not_hold_a_job(self):
        async with await self.session.ws_connect(self.server.make_url(module.MEDIA_PATH)) as ws:
            await asyncio.wait_for(ws.receive(),0.5)
        self.assertEqual(self.observer.handshakes,0)
        self.assertFalse(self.received)

    async def test_duplicate_dispatch_and_second_stream_cannot_start_two_analyses(self):
        self.assertEqual(await self.dispatch(),202)
        self.assertEqual(await self.dispatch(),202)
        await self.streams.started.wait()
        async with await self.twilio() as first:
            for _ in range(100):
                if self.received:break
                await asyncio.sleep(0.005)
            async with await self.twilio() as replay:
                await replay.receive()
            await first.send_json(media())
            await first.receive()
        await self.finish()
        self.assertEqual(len([v for v in self.received if isinstance(v,dict)]),1)
        self.assertEqual(len(self.store.results),1)

    async def test_wrong_call_or_codec_cannot_reach_provider(self):
        await self.dispatch();await self.streams.started.wait()
        async with await self.twilio(callSid='CA'+'e'*32) as ws:await ws.receive()
        self.assertFalse(self.received)
        await self.finish()
        self.assertEqual(len(self.streams.stopped),1)

    async def test_stream_start_timeout_is_recovered_by_name_and_never_retried(self):
        self.streams.fail=True
        await self.dispatch()
        _,result,details=await self.finish()
        self.assertEqual(result.status,'FAILED')
        self.assertEqual(len(self.streams.recovered),1)
        self.assertEqual(len(self.streams.stopped),1)
        self.assertTrue(details['stop_confirmed'])
        self.assertFalse(self.received)

    async def test_unconfirmed_stop_opens_a_circuit_without_pausing_calls(self):
        self.streams.fail=True;self.streams.stop_ok=False
        await self.dispatch();await self.finish()
        self.assertTrue(self.observer.degraded)
        self.store.claims.clear()
        self.assertEqual(await self.dispatch(),202)
        self.assertFalse(self.store.claims)

    async def test_auth_failure_bypasses_new_analysis_until_backoff_expires(self):
        self.answer={'AMDSTATUS':'FAILED','AMDCAUSE':'AUTH_FAILED'}
        self.observer.clock=lambda:100.0
        await self.dispatch();await self.streams.started.wait()
        async with await self.twilio() as ws:
            await ws.send_json(media());await ws.receive()
        await self.finish()
        self.assertEqual(self.observer.backoff_until,130.0)
        self.store.claims.clear()
        await self.dispatch()
        self.assertFalse(self.store.claims)
        self.observer.clock=lambda:131.0
        await self.dispatch()
        self.assertEqual(len(self.store.claims),1)

    async def test_shutdown_stops_active_stream_and_persists_failure(self):
        await self.dispatch();await self.streams.started.wait()
        await self.observer.close()
        self.assertFalse(self.observer.jobs)
        self.assertEqual(len(self.streams.stopped),1)
        self.assertEqual(self.store.results[0][1].status,'FAILED')

    async def test_synchronous_database_failure_never_reaches_provider(self):
        with patch.object(self.store,'claim',side_effect=RuntimeError('private data')):
            with self.assertLogs(module.log,level='WARNING') as logged:
                self.assertEqual(await self.dispatch(),202)
        self.assertFalse(self.received)
        self.assertNotIn('private data',str(logged.output))


if __name__=='__main__':unittest.main()

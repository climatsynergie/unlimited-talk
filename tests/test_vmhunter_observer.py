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
        self.started=asyncio.Event();self.fail=False;self.stop_ok=True;self.terminal=False
    async def start(self,payload,name,token):
        self.token=token;self.started.set()
        if self.fail:raise TimeoutError()
        return 'MZ'+'c'*32
    async def recover(self,call,name):
        self.recovered.append((call,name));return 'MZ'+'c'*32
    async def stop(self,call,stream):self.stopped.append((call,stream));return self.stop_ok
    async def call_finished(self,call):return self.terminal


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

    async def twilio(self,token=None,protocol_version="1.0.0",**changes):
        ws=await self.session.ws_connect(self.server.make_url(module.MEDIA_PATH))
        await ws.send_json({'event':'connected','protocol':'Call','version':protocol_version})
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
        self.assertEqual(details,{'stop_confirmed':True,'audio_stats':dict(pcm_bytes=320,frames=1,signal_frames=0)})
        self.assertEqual(len(self.streams.stopped),1)
        self.assertNotIn('SYNTHETIC-VM-KEY',repr(self.store.results))

    async def test_observed_twilio_0_2_handshake_reaches_provider_and_confirms_cleanup(self):
        # Observed on the owner's real CHIN LIST test on 2026-11-25.
        await self.dispatch()
        await asyncio.wait_for(self.streams.started.wait(),1)
        async with await self.twilio(protocol_version='0.2.0') as ws:
            await ws.send_json(media())
            await ws.receive()
        _,result,details=await self.finish()
        self.assertEqual(result,vm.Result('MACHINE','MACHINE_BEEP'))
        self.assertEqual(self.received[1],b'\0'*320)
        self.assertTrue(details['stop_confirmed'])
        self.assertEqual(len(self.streams.stopped),1)
        self.assertFalse(self.observer.degraded)

    async def test_initial_silence_is_kept_with_content_free_audio_diagnostics(self):
        self.answer={'AMDSTATUS':'MACHINE','AMDCAUSE':'INITIALSILENCE'}
        await self.dispatch();await self.streams.started.wait()
        async with await self.twilio(protocol_version='0.2.0') as ws:
            # Nonzero synthetic samples prove delivery; they do not prove speech.
            import base64
            message=media();message['media']['payload']=base64.b64encode(b'\x00'*160).decode()
            await ws.send_json(message);await ws.receive()
        _,result,details=await self.finish()
        self.assertEqual(result,vm.Result('MACHINE','INITIALSILENCE'))
        self.assertEqual(vm.screen_action(result,stop_confirmed=details['stop_confirmed']),'continue')
        self.assertEqual(details['audio_stats'],dict(pcm_bytes=320,frames=1,signal_frames=1))

    async def test_unknown_protocol_version_is_rejected_without_consuming_valid_job(self):
        await self.dispatch()
        await asyncio.wait_for(self.streams.started.wait(),1)
        async with await self.twilio(protocol_version='2.0.0') as ws:
            await ws.receive()
        self.assertFalse(self.received)
        async with await self.twilio(protocol_version='1.0.0') as ws:
            await ws.send_json(media())
            await ws.receive()
        _,result,details=await self.finish()
        self.assertEqual(result.status,'MACHINE')
        self.assertTrue(details['stop_confirmed'])

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

    async def test_verified_terminal_call_does_not_open_cleanup_circuit(self):
        # The real completed one-second call's stop endpoint returns 400/21220.
        # Only the independently bound authenticated Call GET can release it.
        self.streams.stop_ok=False
        self.streams.call_finished=AsyncMock(return_value=True)
        await self.dispatch()
        await self.streams.started.wait()
        async with await self.twilio(protocol_version='0.2.0') as ws:
            await ws.send_json(media())
            await ws.receive()
        _,result,details=await self.finish()
        self.assertEqual(result,vm.Result('MACHINE','MACHINE_BEEP'))
        self.assertTrue(details['stop_confirmed'])
        self.assertFalse(self.observer.degraded)
        self.streams.call_finished.assert_awaited_once_with(self.payload['call_sid'])

    async def test_terminal_status_read_failure_keeps_safety_circuit_and_result(self):
        self.streams.fail=True;self.streams.stop_ok=False
        self.streams.call_finished=AsyncMock(side_effect=TimeoutError())
        await self.dispatch()
        _,result,details=await self.finish()
        self.assertEqual(result.status,'FAILED')
        self.assertFalse(details['stop_confirmed'])
        self.assertTrue(self.observer.degraded)
        self.streams.call_finished.assert_awaited_once_with(self.payload['call_sid'])

    async def test_late_terminal_proof_recovers_circuit_and_accepts_next_call(self):
        # The real 21:48 timeout occurred while the customer call was still live.
        # A later verified end must recover without an operator or API restart.
        self.streams.fail=True;self.streams.stop_ok=False
        await self.dispatch();await self.finish()
        self.assertTrue(self.observer.degraded)
        pending=list(self.store.claims)
        self.store.cleanup_candidates=lambda:pending.copy()
        self.store.verify_cleanup=lambda payload,status:pending.remove(payload) is None
        self.streams.terminal_status=AsyncMock(return_value=None)
        await self.observer.recover_cleanup()
        self.assertTrue(self.observer.degraded)
        self.assertEqual(len(pending),1)
        self.streams.terminal_status.return_value='completed'
        await self.observer.recover_cleanup()
        self.assertFalse(pending)
        self.assertFalse(self.observer.degraded)
        self.store.claims.clear();self.store.results.clear()
        self.observer.backoff_until=0
        await self.dispatch()
        self.assertEqual(len(self.store.claims),1)

    async def test_recovery_failure_never_clears_unverified_streams(self):
        self.observer.degraded=True
        self.store.cleanup_candidates=lambda:list(self.store.claims) or [self.payload | {'nonce':'a'*32}]
        self.store.verify_cleanup=lambda *_:self.fail('Unverified cleanup must not be persisted')
        self.streams.terminal_status=AsyncMock(side_effect=TimeoutError('private provider body'))
        with self.assertLogs(module.log,level='WARNING') as logs:
            await self.observer.recover_cleanup()
        self.assertTrue(self.observer.degraded)
        self.assertNotIn('private provider body',str(logs.output))

    async def test_provider_only_unknown_or_live_result_cannot_resume_filter(self):
        self.observer.degraded=True
        pending=[self.payload | {'nonce':'a'*32}]
        self.store.cleanup_candidates=lambda:pending.copy()
        self.store.verify_cleanup=lambda *_:False # DB state/binding has not verified terminal.
        self.streams.terminal_status=AsyncMock(return_value='completed')
        await self.observer.recover_cleanup()
        self.assertTrue(self.observer.degraded)
        self.assertEqual(pending,[self.payload | {'nonce':'a'*32}])

    async def test_periodic_recovery_runs_and_stops_with_the_application(self):
        await self.server.close()
        pending=[self.payload | {'nonce':'a'*32}]
        self.store.cleanup_candidates=lambda:pending.copy()
        self.store.verify_cleanup=lambda payload,status:pending.remove(payload) is None
        self.streams.terminal_status=AsyncMock(return_value=None)
        self.server=TestServer(module.application(self.observer,recovery_interval=0.01))
        await self.server.start_server()
        self.assertTrue(self.observer.degraded)
        self.streams.terminal_status.return_value='completed'
        for _ in range(100):
            if not self.observer.degraded:break
            await asyncio.sleep(0.005)
        self.assertFalse(self.observer.degraded)
        self.assertFalse(pending)
        await self.server.close()
        count=self.streams.terminal_status.await_count
        await asyncio.sleep(0.03)
        self.assertEqual(self.streams.terminal_status.await_count,count)

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

    async def test_subscription_health_reports_monthly_provider_allowance_not_old_total_cap(self):
        self.store.provider_quota=module.ProviderQuota()
        async with self.session.get(self.server.make_url('/health/live')) as response:
            self.assertEqual(response.status,200)
            value=await response.json()
        self.assertEqual(value['quota'],dict(source='vmhunter_subscription',monthly_allowance=5000,internal_total_limit=None))
        self.assertTrue(value['accepting'])

    async def test_provider_quota_exhaustion_preserves_calls_and_recovers_after_provider_reset(self):
        self.answer={'AMDSTATUS':'FAILED','AMDCAUSE':'LIMIT_REACHED'}
        self.observer.clock=lambda:100.0
        await self.dispatch();await self.streams.started.wait()
        async with await self.twilio(protocol_version='0.2.0') as ws:
            await ws.send_json(media());await ws.receive()
        _,result,details=await self.finish()
        self.assertEqual(result,vm.Result('FAILED','LIMIT_REACHED'))
        self.assertEqual(vm.screen_action(result,stop_confirmed=details['stop_confirmed']),'continue')
        self.assertFalse(self.observer.degraded)
        self.assertEqual(self.observer.backoff_until,130.0)
        self.store.claims.clear();self.store.results.clear();self.streams.started.clear()
        await self.dispatch();self.assertFalse(self.store.claims)
        self.observer.clock=lambda:131.0
        self.answer={'AMDSTATUS':'HUMAN','AMDCAUSE':'HUMAN'}
        await self.dispatch();await self.streams.started.wait()
        async with await self.twilio(protocol_version='0.2.0') as ws:
            await ws.send_json(media());await ws.receive()
        self.assertEqual((await self.finish())[1],vm.Result('HUMAN','HUMAN'))

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

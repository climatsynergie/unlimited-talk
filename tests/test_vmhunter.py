"""Synthetic protocol/security and real loopback WebSocket regression tests."""
import asyncio
import base64
from dataclasses import replace
import json
import os
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.telephony import vmhunter as vm
from app.telephony import vmhunter_observer as observer
from app.telephony.twilio_voice import ManualVoiceProfile


def policy(**changes):
    return dict(version=1, pilot_id=str(uuid4()), enabled=False, mode='observe',
                campaign_id=str(vm.PILOT_CAMPAIGN), agent_ids=[], max_analyses=500,
                test_numbers=[], audio_approved=False) | changes


def start(**changes):
    return {'event': 'start', 'start': {
        'accountSid': 'AC' + 'a' * 32, 'callSid': 'CA' + 'b' * 32,
        'streamSid': 'MZ' + 'c' * 32, 'tracks': ['inbound'],
        'mediaFormat': {'encoding': 'audio/x-mulaw', 'sampleRate': 8000, 'channels': 1},
        **changes}}


def media(chunk=1, data=b'\xff' * 160, **changes):
    return {'event': 'media', 'streamSid': 'MZ' + 'c' * 32,
        'media': {'track': 'inbound', 'payload': base64.b64encode(data).decode(),
                  'chunk': str(chunk), 'timestamp': str((chunk - 1) * 20), **changes}}


PROFILE = ManualVoiceProfile('AC' + 'a' * 32, 'SK' + 'b' * 32, 'c' * 32, 'AP' + 'd' * 32,
    'webhooks_sharedkey_' + 'e' * 26, 'f' * 32, 'https://voice.example.invalid', '+14165550100')


class ProtocolTests(unittest.TestCase):
    def test_g711_reference_all_256_codes(self):
        # Independent stdlib C implementation available on the supported 3.12 image.
        import audioop
        data = bytes(range(256))
        self.assertEqual(vm.pcm(data), audioop.ulaw2lin(data, 2))
        self.assertEqual(vm.pcm(b'\xff\x7f'), b'\0\0\0\0')

    def test_json_rejects_duplicates_nonobjects_nan_and_oversize(self):
        for raw in ('[]', '{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', 'x'*4097, b'\xff'):
            with self.subTest(raw=raw[:20]), self.assertRaises(vm.ProtocolError): vm.object_json(raw)

    def test_no_unknown_or_uncertain_result_can_hang_up(self):
        for status, causes in {
            'HUMAN': ['HUMAN'], 'MACHINE': ['MACHINE', 'MACHINE_BEEP', 'MACHINE_STATIC',
                'INITIALSILENCE', 'MAXWORD', 'DISCONNECT', 'CALLGUARD_PHRASE:private words'],
            'CALLGUARD': ['CALLGUARD_PHRASE:test'],
            'FAILED': ['AUTH_FAILED', 'LIMIT_REACHED', 'CPS_LIMIT', 'CHANNEL_LIMIT', 'NO_SUBSCRIPTION',
                'PERIOD_EXPIRED', 'CONFIG_TIMEOUT', 'SPEECHLLM_ENGINE_UNAVAILABLE']}.items():
            for cause in causes:
                result = vm.verdict(json.dumps(dict(AMDSTATUS=status, AMDCAUSE=cause)))
                self.assertEqual(result.observation_action, 'continue')
                self.assertNotIn('private words', repr(result))
        for value in [dict(AMDSTATUS='MACHINE', AMDCAUSE='new-provider-value'),
                      dict(AMDSTATUS='HUMAN', AMDCAUSE='MACHINE'), dict(AMDSTATUS=[], AMDCAUSE=1)]:
            with self.assertRaises(vm.ProtocolError): vm.verdict(json.dumps(value))

    def test_pilot_disabled_until_explicit_agents_numbers_and_audio_approval(self):
        p = vm.Pilot.parse(policy())
        self.assertFalse(p.enabled)
        for changes in [dict(enabled=True), dict(enabled=True, agent_ids=[str(uuid4())]),
                        dict(mode='screen'), dict(campaign_id=str(uuid4())), dict(max_analyses=True),
                        dict(max_analyses=1001), dict(agent_ids=[str(uuid4())]*2),
                        dict(agent_ids=[str(uuid4()) for _ in range(3)]),
                        dict(test_numbers=['not-a-number']), dict(enabled=1), dict(unexpected='x')]:
            with self.subTest(changes=changes), self.assertRaises(vm.ProtocolError): vm.Pilot.parse(policy(**changes))

    def test_scope_is_intersection_of_campaign_agent_test_number_and_automatic_answered_call(self):
        agent = uuid4()
        p = vm.Pilot.parse(policy(enabled=True, agent_ids=[str(agent)],
                                 test_numbers=['+14165550101'], audio_approved=True))
        row = dict(campaign_id=vm.PILOT_CAMPAIGN, actor_id=agent, destination='+14165550101',
                   dialer_generation=1, state='answered')
        self.assertTrue(p.includes(row))
        for changes in [dict(campaign_id=uuid4()), dict(actor_id=uuid4()), dict(destination='+14165550102'),
                        dict(dialer_generation=None), dict(state='ringing'), dict(state='finished')]:
            self.assertFalse(p.includes(row | changes))

    def test_tickets_expire_and_are_bound_to_key_purpose_payload(self):
        token = vm.ticket('test-key', 'dispatch', {'id': 'test'}, now=100)
        self.assertEqual(vm.unticket('test-key', 'dispatch', token, now=115), {'id': 'test'})
        for secret, purpose, raw, now in [('wrong-key','dispatch',token,100),
                ('test-key','media',token,100), ('test-key','dispatch',token,116),
                ('test-key','dispatch',token,99), ('test-key','dispatch',token+'x',100),
                ('test-key','dispatch','x'*2049,100), ('test-key','dispatch','a.b.c',100)]:
            with self.assertRaises(vm.ProtocolError): vm.unticket(secret,purpose,raw,now=now)

    def test_audio_rejects_wrong_account_call_track_codec_and_stream(self):
        for changes in [dict(accountSid='AC'+'0'*32), dict(callSid='CA'+'0'*32),
                        dict(tracks=['outbound']), dict(tracks=['inbound','outbound']),
                        dict(mediaFormat={'encoding':'audio/x-mulaw','sampleRate':16000,'channels':1})]:
            with self.assertRaises(vm.ProtocolError):
                vm.Audio(start(**changes),account=PROFILE.account_sid,call='CA'+'b'*32)
        audio=vm.Audio(start(),account=PROFILE.account_sid,call='CA'+'b'*32)
        self.assertEqual(len(audio.feed(media())[0]),320)
        for message in [media(),media(2,track='outbound'),media(2,payload='$$$'),media(2,timestamp='0'),
                        media(3),media(2,data=b'x'*1608),media(2) | {'streamSid':'MZ'+'d'*32}]:
            with self.assertRaises(vm.ProtocolError): audio.feed(message)

    def test_audio_duration_and_memory_are_bounded(self):
        audio=vm.Audio(start(),account=PROFILE.account_sid,call='CA'+'b'*32)
        frames=[]
        for chunk in range(1,177): frames.extend(audio.feed(media(chunk)))
        self.assertEqual(audio.total,28000)
        self.assertEqual(sum(map(len,frames)),56000)
        self.assertLess(len(audio.pending),160)

    def test_stream_rest_client_can_only_target_stream_resources(self):
        client=observer.Streams(PROFILE,None)
        self.assertTrue(client.url('CA'+'1'*32).endswith('/Streams.json'))
        self.assertTrue(client.url('CA'+'1'*32,'MZ'+'2'*32).endswith('/Streams/MZ'+'2'*32+'.json'))
        for call,stream in [('x/../../Calls.json',None),('CA'+'1'*32,'../..')]:
            with self.assertRaises(vm.ProtocolError):client.url(call,stream)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received=[]
        self.finished=asyncio.Event()
        self.answer={'AMDSTATUS':'HUMAN','AMDCAUSE':'HUMAN'}
        self.early=False
        self.silent=False
        self.close_instead=False
        self.port=None

        async def provider(request):
            ws=web.WebSocketResponse()
            await ws.prepare(request)
            try:
                self.received.append(await ws.receive_json())
                if self.early:
                    await ws.send_json(self.answer)
                    return ws
                if self.close_instead:return ws
                async for message in ws:
                    self.received.append(message.data)
                    if message.type==aiohttp.WSMsgType.TEXT and json.loads(message.data)=={'eof':1}:
                        if not self.silent:await ws.send_json(self.answer)
                        if not self.silent:break
            finally:
                await ws.close()
                self.finished.set()
            return ws
        app=web.Application();app.router.add_get('/ws',provider)
        self.server=TestServer(app);await self.server.start_server()
        self.session=aiohttp.ClientSession(trust_env=False)
        self.client=vm.Client('SYNTHETIC-KEY',session=self.session,endpoint=str(self.server.make_url('/ws')).replace('http:','ws:'))

    async def asyncTearDown(self):
        await self.session.close();await self.server.close()

    async def audio(self):
        yield vm.pcm(b'\xff'*160)
        yield vm.pcm(b'\x00'*160)

    async def test_actual_loopback_websocket_config_binary_audio_eof_and_verdict(self):
        result=await self.client.classify(uuid4(),self.audio())
        self.assertEqual(result,vm.Result('HUMAN','HUMAN'))
        self.assertEqual(self.received[0]['config']['api_key'],'SYNTHETIC-KEY')
        self.assertEqual(self.received[0]['config']['sample_rate'],8000)
        self.assertEqual(self.received[1],vm.pcm(b'\xff'*160))
        self.assertEqual(json.loads(self.received[-1]),{'eof':1})

    async def test_early_verdict_cancels_a_sender_waiting_for_more_media(self):
        self.early=True
        closed=asyncio.Event()
        async def waiting():
            try:
                yield b'\0'*320
                await asyncio.Future()
            finally:closed.set()
        self.assertEqual((await self.client.classify(uuid4(),waiting())).status,'HUMAN')
        await asyncio.wait_for(closed.wait(),1)

    async def test_provider_timeout_fails_open_and_closes_socket(self):
        self.silent=True
        result=await self.client.classify(uuid4(),self.audio(),seconds=0.08)
        self.assertEqual(result.status,'FAILED')
        self.assertEqual(result.observation_action,'continue')
        await asyncio.wait_for(self.finished.wait(),1)

    async def test_closed_socket_quota_errors_and_malformed_verdict_fail_open(self):
        self.close_instead=True
        self.assertEqual((await self.client.classify(uuid4(),self.audio())).status,'FAILED')
        self.close_instead=False
        for answer in [{'AMDSTATUS':'FAILED','AMDCAUSE':'LIMIT_REACHED'}, {'unknown':'response'}]:
            self.answer=answer
            result=await self.client.classify(uuid4(),self.audio())
            self.assertEqual(result.status,'FAILED');self.assertEqual(result.observation_action,'continue')

    async def test_audio_validation_failure_cannot_be_hidden_by_successful_eof(self):
        async def odd():yield b'x'
        result=await self.client.classify(uuid4(),odd())
        self.assertEqual(result.status,'FAILED')
        self.assertEqual(result.observation_action,'continue')

    async def test_cancellation_propagates_and_closes_provider_connection(self):
        self.silent=True
        task=asyncio.create_task(self.client.classify(uuid4(),self.audio()))
        for _ in range(100):
            if self.received:break
            await asyncio.sleep(0.005)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        await asyncio.wait_for(self.finished.wait(),1)


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_and_disabled_configuration_never_connect_to_a_provider(self):
        with patch.dict(os.environ,{},clear=True),patch.object(observer.aiohttp,'ClientSession') as network:
            await observer.dispatch(PROFILE,uuid4(),{'CallStatus':'in-progress'})
            network.assert_not_called()
        with patch.dict(os.environ,{'VMHUNTER_PILOT_FILE':'synthetic'}), \
                patch.object(observer,'policy_from_file',return_value=vm.Pilot.parse(policy())), \
                patch.object(observer.aiohttp,'ClientSession') as network:
            await observer.dispatch(PROFILE,uuid4(),{'CallStatus':'in-progress'})
            network.assert_not_called()

    async def test_invalid_config_does_not_fail_call_callback(self):
        with patch.dict(os.environ,{'VMHUNTER_PILOT_FILE':'synthetic'}), \
                patch.object(observer,'policy_from_file',side_effect=ValueError('secret-must-not-log')), \
                self.assertLogs(observer.log,level='WARNING') as logged:
            await observer.dispatch(PROFILE,uuid4(),{'CallStatus':'in-progress'})
        self.assertNotIn('secret-must-not-log',str(logged.output))

    async def test_observer_connection_failure_does_not_fail_call_callback(self):
        pilot=vm.Pilot.parse(policy(enabled=True,agent_ids=[str(uuid4())],audio_approved=True,
                                   test_numbers=['+14165550101']))
        with patch.dict(os.environ,{'VMHUNTER_PILOT_FILE':'synthetic'}), \
                patch.object(observer,'policy_from_file',return_value=pilot), \
                patch.object(observer.aiohttp,'ClientSession',side_effect=OSError('private details')), \
                self.assertLogs(observer.log,level='WARNING') as logged:
            await observer.dispatch(PROFILE,uuid4(),{'CallStatus':'in-progress','CallSid':'CA'+'1'*32})
        self.assertNotIn('private details',str(logged.output))


if __name__=='__main__':unittest.main()

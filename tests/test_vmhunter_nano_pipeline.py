"""Twenty simultaneous, bound media sockets through a real loopback provider."""
import asyncio
import hashlib
import time
import unittest
from types import SimpleNamespace
from uuid import uuid4

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.telephony import vmhunter as vm
from app.telephony import vmhunter_observer as module
from test_vmhunter import PROFILE, policy, start, media


class NanoPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_twenty_bound_calls_stream_and_cleanup_under_five_cps(self):
        configs, results, stopped, media_tasks = [], [], [], []
        twenty_ready = asyncio.Event()
        release = asyncio.Event()
        async def provider(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            try:
                config = await ws.receive_json()
                self.assertEqual(config['config']['sample_rate'], 8000)
                self.assertEqual(config['config']['bytes_per_sample'], 2)
                configs.append((time.monotonic(), config['config']['vid']))
                frame = await ws.receive()
                self.assertEqual(frame.type, aiohttp.WSMsgType.BINARY)
                self.assertEqual(len(frame.data), 320)
                if len(configs) == 20:
                    twenty_ready.set()
                await release.wait()
                await ws.send_json({'AMDSTATUS': 'HUMAN', 'AMDCAUSE': 'HUMAN'})
            finally:
                await ws.close()
            return ws
        upstream_app = web.Application()
        upstream_app.router.add_get('/ws', provider)
        upstream = TestServer(upstream_app)
        await upstream.start_server()
        session = aiohttp.ClientSession()
        pilot = vm.Pilot.parse(policy(version=3, scope='campaign', mode='screen', enabled=True,
            audio_approved=True, screening_approved=True))
        quota = module.ProviderQuota(100000)
        claims = []
        def claim(payload):
            value = payload | {'nonce': uuid4().hex}
            claims.append(value)
            return value
        store = SimpleNamespace(provider_quota=quota, claim=claim,
            result=lambda payload, result, **detail: results.append((payload, result, detail)))
        server = None
        async def far_end(payload, stream, token):
            async with session.ws_connect(server.make_url(module.MEDIA_PATH)) as ws:
                await ws.send_json({'event': 'connected', 'protocol': 'Call', 'version': '0.2.0'})
                await ws.send_json(start(callSid=payload['call_sid'], streamSid=stream,
                    customParameters={'ticket': token}))
                frame = media()
                frame['streamSid'] = stream
                await ws.send_json(frame)
                await ws.receive()
        class Streams:
            async def start(self, payload, name, token):
                stream = 'MZ' + hashlib.md5(payload['nonce'].encode()).hexdigest()
                media_tasks.append(asyncio.create_task(far_end(payload, stream, token)))
                return stream
            async def stop(self, call, stream):
                stopped.append((call, stream))
                return True
        provider_client = vm.Client('SYNTHETIC-NANO-KEY', session=session,
            endpoint=str(upstream.make_url('/ws')).replace('http:', 'ws:'),
            start_limiter=vm.StartLimiter(5))
        observer = module.Observer(PROFILE, pilot, store, Streams(), provider_client)
        server = TestServer(module.application(observer))
        await server.start_server()
        async def dispatch():
            payload = dict(intent_id=str(uuid4()), call_sid='CA' + uuid4().hex,
                           pilot_id=str(pilot.identifier))
            token = vm.ticket(PROFILE.shared_key_secret, 'dispatch', payload)
            async with session.post(server.make_url('/private/observe'), json={'ticket': token}) as response:
                self.assertEqual(response.status, 202)
                self.assertTrue((await response.json())['accepted'])
        try:
            for batch in range(4):
                if batch:
                    await asyncio.sleep(1.1)
                await asyncio.gather(*(dispatch() for _ in range(5)))
            await asyncio.wait_for(twenty_ready.wait(), 1)
            self.assertEqual(len(configs), 20)
            self.assertEqual(len(observer.jobs), 20)
            for at, _ in configs:
                self.assertLessEqual(sum(at <= other < at + 1 for other, _ in configs), 5)
            self.assertEqual(len({vid for _, vid in configs}), 20)
            release.set()
            for _ in range(200):
                if len(results) == 20 and not observer.jobs:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(len(results), 20)
            self.assertEqual(len(stopped), 20)
            self.assertTrue(all(result == vm.Result('HUMAN', 'HUMAN') and detail['stop_confirmed']
                                and detail['audio_stats']['pcm_bytes'] == 320
                                for _, result, detail in results))
            self.assertFalse(observer.jobs)
            self.assertFalse(observer.degraded)
            self.assertNotIn('SYNTHETIC-NANO-KEY', repr(results))
            await asyncio.gather(*media_tasks)
        finally:
            release.set()
            await server.close()
            for task in media_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*media_tasks, return_exceptions=True)
            await session.close()
            await upstream.close()

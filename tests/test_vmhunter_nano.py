"""Nano entitlement, bounded admission and actual config-frame rate regressions."""
import asyncio
import json
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.telephony import vmhunter as vm
from app.telephony import vmhunter_observer as module
from test_vmhunter import PROFILE, policy


class NanoQuotaTests(unittest.TestCase):
    def test_explicit_nano_subscription_loads_without_rejecting_paid_allowance(self):
        pilot = vm.Pilot.parse(policy(version=3, scope='campaign', mode='screen', enabled=True,
            audio_approved=True, screening_approved=True))
        with patch.dict(os.environ, {'VMHUNTER_QUOTA_SOURCE': 'provider',
                'VMHUNTER_MONTHLY_ALLOWANCE': '100000'}, clear=True):
            quota = module.ProviderQuota.from_environment(pilot)
        self.assertEqual(quota.monthly_allowance, 100000)
        self.assertEqual(quota.max_concurrent, 20)
        self.assertEqual(quota.calls_per_second, 5)
        self.assertEqual(quota.provider_channels, 50)

    def test_free_configuration_keeps_its_existing_two_analysis_capacity(self):
        quota = module.ProviderQuota()
        self.assertEqual(quota.monthly_allowance, 5000)
        self.assertEqual(quota.max_concurrent, 2)

    def test_unknown_allowances_and_boolean_values_still_fail_closed(self):
        for count in (True, 100000.0, '100000', 99999, 100001, 300000, -1):
            with self.subTest(count=count), self.assertRaises(ValueError):
                module.ProviderQuota(count)


class NanoObserverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pilot = vm.Pilot.parse(policy(version=3, scope='campaign', mode='screen', enabled=True,
            audio_approved=True, screening_approved=True))
        self.claims = []
        self.gate = threading.Event()
        self.gate.set()
        def claim(payload):
            if not self.gate.wait(3):
                raise TimeoutError('synthetic admission fixture stalled')
            value = payload | {'nonce': uuid4().hex}
            self.claims.append(value)
            return value
        self.store = SimpleNamespace(claim=claim, provider_quota=SimpleNamespace(
            monthly_allowance=100000, max_concurrent=20, calls_per_second=5, provider_channels=50))
        self.observer = module.Observer(PROFILE, self.pilot, self.store, None, None)
        async def hold(job):
            await asyncio.sleep(30)
        self.observer.run = hold
        self.server = TestServer(module.application(self.observer))
        await self.server.start_server()
        self.session = aiohttp.ClientSession()

    async def asyncTearDown(self):
        self.gate.set()
        await self.server.close()
        await self.session.close()

    async def dispatch(self):
        payload = dict(intent_id=str(uuid4()), call_sid='CA' + uuid4().hex,
                       pilot_id=str(self.pilot.identifier))
        token = vm.ticket(PROFILE.shared_key_secret, 'dispatch', payload)
        async with self.session.post(self.server.make_url('/private/observe'),
                                     json={'ticket': token}) as response:
            self.assertEqual(response.status, 202)
            return await response.json()

    async def test_third_simultaneous_analysis_is_not_bypassed_for_nano(self):
        for _ in range(3):
            self.assertTrue((await self.dispatch())['accepted'])
        self.assertEqual(len(self.claims), 3)

    async def test_nano_burst_is_limited_before_database_await(self):
        self.gate.clear()
        tasks = [asyncio.create_task(self.dispatch()) for _ in range(25)]
        try:
            for _ in range(200):
                if sum(t.done() for t in tasks) >= 5:
                    break
                await asyncio.sleep(0.005)
            self.gate.set()
            answers = await asyncio.gather(*tasks)
            self.assertEqual(sum(x['accepted'] for x in answers), 5)
            self.assertEqual(len(self.claims), 5)
        finally:
            self.gate.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_parallel_admissions_reserve_capacity_before_database_await(self):
        # Free has no new CPS gate; competing awaits must still respect its
        # existing two slots rather than each observing both as available.
        self.store.provider_quota = module.ProviderQuota()
        self.observer.admission_limiter = None
        self.gate.clear()
        tasks = [asyncio.create_task(self.dispatch()) for _ in range(8)]
        try:
            for _ in range(200):
                if sum(t.done() for t in tasks) >= 6:
                    break
                await asyncio.sleep(0.005)
            self.gate.set()
            answers = await asyncio.gather(*tasks)
            self.assertEqual(sum(x['accepted'] for x in answers), 2)
            self.assertEqual(len(self.claims), 2)
        finally:
            self.gate.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_health_discloses_nano_allowance_and_effective_local_capacity(self):
        async with self.session.get(self.server.make_url('/health/live')) as response:
            data = await response.json()
        self.assertEqual(data['quota'], dict(source='vmhunter_subscription',
            monthly_allowance=100000, internal_total_limit=None))
        self.assertEqual(data['capacity'], dict(max_concurrent=20, calls_per_second=5,
            provider_channels=50))


class NanoRateTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_config_frames_cannot_exceed_five_in_a_rolling_second(self):
        received = []
        async def provider(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            message = await ws.receive()
            if message.type == aiohttp.WSMsgType.TEXT:
                received.append(json.loads(message.data)['config']['vid'])
                await ws.send_json({'AMDSTATUS': 'HUMAN', 'AMDCAUSE': 'HUMAN'})
            await ws.close()
            return ws
        app = web.Application()
        app.router.add_get('/ws', provider)
        server = TestServer(app)
        await server.start_server()
        now = [10.9]
        async def audio():
            yield bytes(320)
        try:
            async with aiohttp.ClientSession() as session:
                limiter = vm.StartLimiter(5, clock=lambda: now[0])
                client = vm.Client('SYNTHETIC', session=session,
                    endpoint=str(server.make_url('/ws')).replace('http:', 'ws:'),
                    start_limiter=limiter)
                results = await asyncio.gather(*(client.classify(str(i), audio()) for i in range(6)))
                self.assertEqual(len(received), 5)
                self.assertEqual(sum(r.status == 'HUMAN' for r in results), 5)
                self.assertEqual(sum(r.cause == 'local_rate_limit' for r in results), 1)
                now[0] = 11.1  # Crossing a wall-clock second must not reset the window.
                result = await client.classify('still-limited', audio())
                self.assertEqual(result.cause, 'local_rate_limit')
                self.assertEqual(len(received), 5)
                self.assertEqual(vm.screen_action(result, stop_confirmed=True), 'continue')
                now[0] = 11.901
                self.assertEqual((await client.classify('next-window', audio())).status, 'HUMAN')
                self.assertEqual(len(received), 6)
        finally:
            await server.close()

    async def test_invalid_rate_configuration_is_rejected(self):
        for rate in (True, 0, 6, '5', 5.0):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                vm.StartLimiter(rate)


class NanoFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_rate_bypass_does_not_start_a_global_provider_failure_backoff(self):
        from test_vmhunter_observer import Store, Streams
        store, streams = Store(), Streams()
        pilot = vm.Pilot.parse(policy(enabled=True, agent_ids=[str(uuid4())], audio_approved=True,
            test_numbers=['+14165550101']))
        observer = module.Observer(PROFILE, pilot, store, streams, None, clock=lambda: 100.0)
        payload = dict(intent_id=str(uuid4()), call_sid='CA' + uuid4().hex,
            pilot_id=str(pilot.identifier), nonce=uuid4().hex)
        done = asyncio.get_running_loop().create_future()
        done.set_result(vm.Result('FAILED', 'local_rate_limit'))
        job = {'payload': payload, 'stream': None, 'socket': None, 'done': done}
        observer.jobs[payload['nonce']] = job
        await observer.run(job)
        self.assertEqual(observer.backoff_until, 0.0)
        self.assertFalse(observer.degraded)
        self.assertTrue(store.results[0][2]['stop_confirmed'])
        self.assertEqual(vm.screen_action(store.results[0][1], stop_confirmed=True), 'continue')

    async def test_cleanup_failure_logs_sqlstate_without_sql_credentials_or_parameters(self):
        from sqlalchemy.exc import OperationalError
        secret = 'private_sql_credential_and_parameters'
        original = RuntimeError(secret)
        original.sqlstate = '57014'
        error = OperationalError(secret, {'password': secret}, original)
        def failing(**_):
            raise error
        observer = module.Observer(PROFILE, None, SimpleNamespace(cleanup_candidates=failing), None, None)
        with self.assertLogs(module.log, level='WARNING') as capture:
            await observer.recover_cleanup()
        self.assertTrue(observer.degraded)
        self.assertIn('sqlstate=57014', '\n'.join(capture.output))
        self.assertNotIn(secret, '\n'.join(capture.output))
        observer.store.cleanup_candidates = lambda **_: []
        await observer.recover_cleanup()
        self.assertFalse(observer.degraded)

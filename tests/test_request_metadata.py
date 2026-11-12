"""Operational references remain useful without logging customer data or secrets."""
import json
from types import SimpleNamespace
import unittest
from fastapi.responses import JSONResponse
from app.main import request_metadata


class RequestMetadataTests(unittest.IsolatedAsyncioTestCase):
    def request(self):
        return SimpleNamespace(method='POST',url=SimpleNamespace(path='/api/campaigns/private-customer-id/move'),
            state=SimpleNamespace(actor_id='actor-qa'),scope={'route':SimpleNamespace(path='/api/campaigns/{identifier}/move')})

    async def test_expected_conflict_is_correlated_with_an_actor_and_a_safe_route(self):
        async def next_response(request):return JSONResponse(status_code=409,content={'detail':'Conflict'},headers={'X-Error-Code':'stale_campaign_contact'})
        with self.assertLogs('uvicorn.error',level='INFO') as captured:
            response=await request_metadata(self.request(),next_response)
        record=json.loads(captured.records[0].getMessage())
        self.assertEqual(record['request_id'],response.headers['X-Request-ID'])
        self.assertEqual(record['actor_id'],'actor-qa')
        self.assertEqual(record['error_code'],'stale_campaign_contact')
        self.assertEqual(record['route'],'/api/campaigns/{identifier}/move')
        self.assertNotIn('private-customer-id',captured.records[0].getMessage())

    async def test_fast_successful_polls_do_not_hide_incidents_in_log_rotation(self):
        async def next_response(request):return JSONResponse({'ok':True})
        with self.assertNoLogs('uvicorn.error',level='INFO'):
            response=await request_metadata(self.request(),next_response)
        self.assertEqual(response.status_code,200)
        self.assertRegex(response.headers['X-Request-ID'],'^[0-9a-f]{32}$')

    async def test_unexpected_failure_has_a_reference_without_sensitive_error_text(self):
        async def next_response(request):raise RuntimeError('PRIVATE_PASSWORD_AND_CLIENT_PHONE')
        with self.assertLogs('uvicorn.error',level='ERROR') as captured:
            response=await request_metadata(self.request(),next_response)
        record=json.loads(captured.records[0].getMessage())
        self.assertEqual(response.status_code,500)
        self.assertEqual(record['exception_type'],'RuntimeError')
        self.assertTrue(record['frames'])
        self.assertEqual(record['request_id'],response.headers['X-Request-ID'])
        self.assertNotIn('PRIVATE_PASSWORD_AND_CLIENT_PHONE',str(captured.output)+response.body.decode())

    async def test_database_failure_keeps_app_query_site_beyond_library_tail_and_safe_sqlstate(self):
        from pathlib import Path
        import app.main as main
        from sqlalchemy.exc import OperationalError
        class DriverFailure(Exception):
            sqlstate = '57014'
        failure = OperationalError('SELECT PRIVATE_CLIENT_SQL', {'phone': 'PRIVATE_PHONE'},
                                   DriverFailure('PRIVATE_DATABASE_MESSAGE'))
        library = {}
        exec(compile('def execute(error, depth):\n if depth: return execute(error, depth-1)\n raise error\n',
                     '/usr/local/lib/python3.12/site-packages/sqlalchemy/engine/base.py', 'exec'), library)
        site = {'execute': library['execute']}
        exec(compile('def reserve_candidate(error):\n execute(error, 12)\n',
                     str(Path(main.__file__).resolve().parent/'telephony'/'dialer_service.py'), 'exec'), site)
        async def next_response(request): site['reserve_candidate'](failure)
        with self.assertLogs('uvicorn.error', level='ERROR') as captured:
            response = await request_metadata(self.request(), next_response)
        record = json.loads(captured.records[0].getMessage())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(record['exception_type'], 'OperationalError')
        self.assertEqual(record['sqlstate'], '57014')
        self.assertEqual(len(record['frames']), 10)
        self.assertTrue(all(frame['file'] == 'base.py' for frame in record['frames']))
        self.assertTrue(any(frame['function'] == 'reserve_candidate' and frame['line'] == 2
                            and frame['file'].endswith('dialer_service.py') for frame in record['app_frames']))
        self.assertLessEqual(len(record['app_frames']), 10)
        self.assertTrue(all(set(frame) == {'file', 'line', 'function'} for frame in record['app_frames']))
        for secret in ('PRIVATE_CLIENT_SQL', 'PRIVATE_PHONE', 'PRIVATE_DATABASE_MESSAGE',
                       '/usr/local/', 'private-customer-id'):
            self.assertNotIn(secret, str(captured.output)+response.body.decode())

    async def test_only_dbapi_errors_can_log_strict_sqlstate_and_never_driver_text(self):
        from sqlalchemy.exc import OperationalError
        for code in ['57014\nPRIVATE_SECRET', 'private', '5701', '570140', '57p03', ' 57014', '57014 ', 57014, None, {'sql': 'PRIVATE_SECRET'}]:
            class DriverFailure(Exception): pass
            original = DriverFailure('PRIVATE_SECRET'); original.sqlstate = code
            failure = OperationalError('PRIVATE_SQL', {'token':'PRIVATE_TOKEN'}, original)
            async def next_response(request): raise failure
            with self.subTest(code=code), self.assertLogs('uvicorn.error', level='ERROR') as captured:
                response = await request_metadata(self.request(), next_response)
            record = json.loads(captured.records[0].getMessage())
            self.assertNotIn('sqlstate', record)
            self.assertIn('app_frames', record)
            self.assertNotIn('PRIVATE_', str(captured.output)+response.body.decode())
        failure = RuntimeError('PRIVATE_SECRET'); failure.sqlstate = '57014'
        async def next_response(request): raise failure
        with self.assertLogs('uvicorn.error', level='ERROR') as captured:
            await request_metadata(self.request(), next_response)
        self.assertNotIn('sqlstate', json.loads(captured.records[0].getMessage()))

    async def test_app_frames_are_bounded_and_do_not_classify_outside_lookalike_directories(self):
        from pathlib import Path
        import app.main as main
        root = Path(main.__file__).resolve().parent
        outside = {}
        exec(compile('def external(error):\n raise error\n', str(root.parent/'app-lookalike'/'query.py'), 'exec'), outside)
        inside = {'external':outside['external']}
        exec(compile('def repeat(error, depth):\n if depth: return repeat(error, depth-1)\n external(error)\n',
                     str(root/'telephony'/'dialer_service.py'), 'exec'), inside)
        async def next_response(request): inside['repeat'](RuntimeError('PRIVATE_SECRET'), 20)
        with self.assertLogs('uvicorn.error', level='ERROR') as captured:
            await request_metadata(self.request(), next_response)
        record = json.loads(captured.records[0].getMessage())
        self.assertEqual(len(record['app_frames']), 10)
        self.assertTrue(all(frame['file'].endswith('dialer_service.py') for frame in record['app_frames']))
        self.assertTrue(all(frame['function'] == 'repeat' for frame in record['app_frames']))
        self.assertNotIn('PRIVATE_SECRET', str(captured.output))

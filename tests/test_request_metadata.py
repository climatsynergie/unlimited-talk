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

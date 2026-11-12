"""Pause diagnostics are bounded client claims, never permissions or customer text."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError
from fastapi import HTTPException
from app.telephony.dialer_routes import Control,control


class PauseDiagnosticTests(unittest.TestCase):
    def body(self,**extra):
        return Control(browser_id=uuid4(),action='pause',generation=2,**extra)

    def test_valid_cause_is_recorded_separately_without_changing_pause_or_actor(self):
        actor={'id':uuid4()};campaign=uuid4();db=object()
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            engine=SimpleNamespace(begin=lambda:nullcontext(db)))))
        body=self.body(pause_cause='sdk_device',failure_code=53000)
        paused={'mode':'paused','generation':3,'campaign_id':str(campaign)}
        with patch('app.telephony.dialer_routes.identity.authenticate',return_value=actor),\
             patch('app.telephony.dialer_routes.dialer.control',return_value=paused) as operation,\
             patch('app.telephony.dialer_routes.identity.audit') as audit:
            self.assertEqual(control(body,request),{'dialer':paused})
        self.assertEqual(operation.call_args.args[1],actor)
        self.assertEqual(operation.call_args.args[3],'pause')
        audit.assert_called_once_with(db,actor['id'],'dialer.pause_cause.sdk_device.53000',str(campaign))

    def test_old_clients_remain_valid_and_do_not_invent_a_pause_cause(self):
        db=object();actor={'id':uuid4()}
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            engine=SimpleNamespace(begin=lambda:nullcontext(db)))))
        with patch('app.telephony.dialer_routes.identity.authenticate',return_value=actor),\
             patch('app.telephony.dialer_routes.dialer.control',return_value={'mode':'paused'}),\
             patch('app.telephony.dialer_routes.identity.audit') as audit:
            control(self.body(),request)
        audit.assert_not_called()

    def test_diagnostics_cannot_be_written_before_authentication_and_control_succeed(self):
        for boundary,status in [('authenticate',401),('control',409)]:
            with self.subTest(boundary=boundary):
                db=object();actor={'id':uuid4()}
                request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
                    engine=SimpleNamespace(begin=lambda:nullcontext(db)))))
                with patch('app.telephony.dialer_routes.identity.authenticate',return_value=actor) as authenticate,\
                     patch('app.telephony.dialer_routes.dialer.control') as operation,\
                     patch('app.telephony.dialer_routes.identity.audit') as audit:
                    (authenticate if boundary=='authenticate' else operation).side_effect=HTTPException(status,'Denied')
                    with self.assertRaises(HTTPException):
                        control(self.body(pause_cause='sdk_device',failure_code=53000),request)
                audit.assert_not_called()

    def test_untrusted_free_text_codes_and_nonpause_diagnostics_are_rejected(self):
        for invalid in [dict(pause_cause='PRIVATE_CUSTOMER_OR_SECRET'),
                        dict(pause_cause='sdk_device',failure_code='53000'),
                        dict(pause_cause='sdk_device',failure_code=True),
                        dict(pause_cause='sdk_device',failure_code=-1),
                        dict(pause_cause='sdk_device',failure_code=100000),
                        dict(failure_code=500)]:
            with self.subTest(invalid=invalid),self.assertRaises(ValidationError):self.body(**invalid)
        with self.assertRaises(ValidationError):
            Control(browser_id=uuid4(),action='stop',generation=2,pause_cause='sdk_device')

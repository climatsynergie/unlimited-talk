"""Real incoming UI/API/PostgreSQL fixture; only provider/media I/O is synthetic.

Imported fixture guards refuse managed databases and enabled communications.
This module is mounted only into the disposable local test container.
"""
from dataclasses import replace
import hashlib
import time
from uuid import UUID, uuid4
from xml.etree import ElementTree

from fastapi import HTTPException, Request
import uvicorn

import agent_workflow_server as base
from app.identity.service import query
from app.telephony.incoming_settlement import process_once

app, engine, scenarios = base.app, base.engine, base.scenarios
with engine.connect() as db:
    assert query(db, 'SELECT version_num FROM staging.alembic_version').scalar_one() == '0012_incoming_runtime'
    for suffix in range(100, 1000):
        phone = '+1416555' + str(suffix).zfill(4)
        if not query(db, 'SELECT 1 FROM staging.inbound_queues WHERE phone=:phone', phone=phone).first():
            break
    else:
        raise RuntimeError('Synthetic receiving phone range exhausted')
base.profile = replace(base.profile, caller_number=phone)
profile = base.profile


def scenario(actor):
    result = scenarios.get(str(actor))
    if not result or 'queue' not in result:
        raise HTTPException(404, 'Scénario synthétique introuvable.')
    return result


def call_row(identifier):
    with engine.connect() as db:
        row = query(db, 'SELECT * FROM staging.inbound_calls WHERE id=:id AND account_sid=:account',
                    id=identifier, account=profile.account_sid).mappings().first()
    if row is None:
        raise HTTPException(404, 'Appel synthétique introuvable.')
    return dict(row)


@app.post('/api/__qa/incoming/bootstrap', include_in_schema=False)
def bootstrap(request: Request):
    base.guard(request)
    result = base.bootstrap(request)
    actor = UUID(result['actor'])
    queue = uuid4()
    name = 'Réception navigateur QA ' + hashlib.sha256(base.control.encode()).hexdigest()[:16] + ' ' + str(queue)[:8]
    with engine.begin() as db:
        admin = query(db, 'SELECT created_by FROM staging.campaigns WHERE id=:id', id=UUID(result['campaign'])).scalar_one()
        query(db, '''INSERT INTO staging.inbound_queues(id,name,phone,timezone,created_by)
            VALUES (:id,:name,:phone,'America/Toronto',:admin)''', id=queue, name=name, phone=phone, admin=admin)
        query(db, '''INSERT INTO staging.inbound_queue_agents(queue_id,user_id,mode,assigned_by)
            VALUES (:queue,:actor,'mixed',:admin)''', queue=queue, actor=actor, admin=admin)
        query(db, '''INSERT INTO staging.inbound_lines(queue_id,account_sid,provider_sid,phone,public_origin,route_state,verified_at)
            VALUES (:queue,:account,:provider,:phone,:origin,'active',clock_timestamp())''', queue=queue,
              account=profile.account_sid, provider='PN' + uuid4().hex, phone=phone, origin=profile.public_origin)
    scenarios[str(actor)].update(queue=str(queue), queue_name=name, incoming={})
    return {**result, 'queue': str(queue), 'queue_name': name, 'receiving_phone': phone}


def receive(actor, caller):
    fixture = scenario(actor)
    fields = dict(CallSid='CA' + uuid4().hex, From=caller, To=phone, Direction='inbound', CallStatus='ringing')
    xml = ElementTree.fromstring(base.signed('incoming', None, fields))
    identifier = UUID(xml.find('Redirect').text.rsplit('/', 1)[1])
    fixture['incoming'][str(identifier)] = fields
    assert str(call_row(identifier)['queue_id']) == fixture['queue']
    return identifier, fields


@app.post('/api/__qa/incoming/{actor}/ring', include_in_schema=False)
def ring(actor: UUID, request: Request):
    base.guard(request)
    identifier, fields = receive(actor, '+16135550191')
    # Registration's visible ready signal can precede its final heartbeat. The
    # carrier normally redirects while waiting; exercise that same real path.
    deadline = time.monotonic() + 5
    while True:
        xml = ElementTree.fromstring(base.signed('incoming-step', identifier, fields))
        client = xml.find('Dial/Client')
        if client is not None or time.monotonic() >= deadline:
            break
        time.sleep(.05)
    assert client is not None, 'A real registered, available browser must receive a canonical offer'
    parameter = client.find("Parameter[@name='Offer']")
    offer_id = UUID(parameter.attrib['value'])
    with engine.connect() as db:
        offer = query(db, 'SELECT * FROM staging.inbound_offers WHERE id=:id', id=offer_id).mappings().one()
        assert offer['actor_id'] == actor and offer['state'] == 'offered'
    return dict(call_id=str(identifier), offer_id=str(offer_id), caller=fields['From'], called=phone)


@app.post('/api/__qa/incoming/{actor}/calls/{identifier}/{action}', include_in_schema=False)
def provider(actor: UUID, identifier: UUID, action: str, request: Request):
    base.guard(request)
    fields = scenario(actor)['incoming'].get(str(identifier))
    if fields is None:
        raise HTTPException(404, 'Appel hors du scénario synthétique.')
    call = call_row(identifier)
    with engine.connect() as db:
        offer = query(db, 'SELECT * FROM staging.inbound_offers WHERE id=:id', id=call['current_offer_id']).mappings().one()
    assert offer['actor_id'] == actor
    child = offer['child_call_sid'] or 'CA' + uuid4().hex
    child_fields = dict(CallSid=child, ParentCallSid=fields['CallSid'], From=phone, To='client:' + offer['client_identity'])
    if action == 'answer':
        assert offer['state'] == 'accepted' and offer['accepted_at'] is not None, 'UI must accept through the real API first'
        xml = ElementTree.fromstring(base.signed('incoming-agent-answer', offer['id'], child_fields))
        assert xml.find('Hangup') is None
        base.signed('incoming-agent-status', offer['id'], {**child_fields, 'CallStatus': 'in-progress', 'SequenceNumber': '1'})
        assert call_row(identifier)['state'] == 'connected'
    elif action == 'finish':
        assert call['state'] == 'connected' and offer['accepted_at'] is not None
        base.signed('incoming-agent-status', offer['id'], {**child_fields, 'CallStatus': 'completed', 'CallDuration': '30', 'SequenceNumber': '2'})
        base.signed('incoming-dial-finish', offer['id'], dict(CallSid=fields['CallSid'], DialCallSid=child,
                    DialCallStatus='completed', DialCallDuration='30', DialBridged='true'))
        base.signed('incoming-parent-status', None, {**fields, 'CallStatus': 'completed', 'CallDuration': '30'})
        assert call_row(identifier)['state'] == 'finished' and call_row(identifier)['outcome'] == 'answered'
    else:
        raise HTTPException(404, 'Action synthétique inconnue.')
    return {'ok': True}


@app.post('/api/__qa/incoming/{actor}/missed', include_in_schema=False)
def missed(actor: UUID, request: Request):
    base.guard(request)
    identifier, fields = receive(actor, '+16135550192')
    xml = ElementTree.fromstring(base.signed('incoming-step', identifier, fields))
    assert xml.find('Dial') is None, 'Paused reception must not receive another offer'
    base.signed('incoming-parent-status', None, {**fields, 'CallStatus': 'completed', 'CallDuration': '1'})
    assert process_once(engine, profile) == 1 and process_once(engine, profile) == 0
    row = call_row(identifier)
    assert row['state'] == 'finished' and row['followup_id'] is not None
    return dict(call_id=str(identifier), followup_id=str(row['followup_id']), caller=fields['From'])


@app.get('/api/__qa/incoming/{actor}/state', include_in_schema=False)
def state(actor: UUID, request: Request):
    base.guard(request)
    fixture = scenario(actor)
    with engine.connect() as db:
        calls = query(db, '''SELECT id,state,outcome,agent_id,followup_id FROM staging.inbound_calls
            WHERE queue_id=:queue ORDER BY received_at,id''', queue=UUID(fixture['queue'])).mappings().all()
        offers = query(db, '''SELECT o.id,o.call_id,o.state,o.accepted_at,o.connected_at,o.terminal_at FROM staging.inbound_offers o
            JOIN staging.inbound_calls c ON c.id=o.call_id WHERE c.queue_id=:queue''', queue=UUID(fixture['queue'])).mappings().all()
        followups = query(db, 'SELECT id,stage,caller_number FROM staging.inbound_followups WHERE queue_id=:queue',
                          queue=UUID(fixture['queue'])).mappings().all()
    return dict(calls=[dict(row) for row in calls], offers=[dict(row) for row in offers], followups=[dict(row) for row in followups])


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000, log_level='warning', access_log=False)

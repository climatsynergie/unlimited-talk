"""Bridge an assigned inbound follow-up to the normal qualification/calendar flow."""
import re
from uuid import uuid4, uuid5
from fastapi import HTTPException
from app.identity.service import query
from app.campaigns import service as campaigns
from app.qualification import SCHEMA, contact_snapshot
from app.telephony import inbound_service as inbound


def call_source(db, actor, identifier):
    from app.telephony.incoming_schema import installed
    if not installed(db):
        raise HTTPException(404, 'Appel entrant introuvable.')
    row = query(db,'SELECT id,queue_id,caller_number FROM staging.inbound_calls WHERE id=:id',id=identifier).mappings().first()
    if row is None:
        raise HTTPException(404, 'Appel entrant introuvable.')
    inbound.queue(db,actor,row['queue_id'])
    return dict(row)


def available(db, actor, identifier, search='', offset=0, *, call=False):
    row = call_source(db,actor,identifier) if call else inbound.followup(db, actor, identifier)
    rows = query(db, '''SELECT ca.id,ca.name,ca.timezone,EXISTS(
        SELECT 1 FROM staging.campaign_contacts m JOIN staging.contacts c ON c.id=m.contact_id
        WHERE m.campaign_id=ca.id AND m.is_active AND c.phone=:phone) AS already_enrolled
        FROM staging.campaigns ca WHERE ca.is_active
        AND (:admin OR EXISTS(SELECT 1 FROM staging.campaign_agents ag
            WHERE ag.campaign_id=ca.id AND ag.user_id=:actor AND ag.is_active))
        AND strpos(lower(ca.name),lower(:search))>0
        ORDER BY already_enrolled DESC,lower(ca.name),ca.id LIMIT 51 OFFSET :offset''',
        phone=row['caller_number'], admin=actor['role']=='admin', actor=actor['id'], search=search, offset=offset).mappings().all()
    return {'items':[dict(r) for r in rows[:50]], 'has_more':len(rows)>50}


def eligible_followup(row, actor):
    if not row['caller_number'] or not re.fullmatch(r'\+[1-9][0-9]{8,14}', row['caller_number']):
        raise HTTPException(409, 'Un numéro identifiable est nécessaire pour ouvrir cette fiche client.')
    if row['stage']=='handled':
        raise HTTPException(409, 'Ce suivi est déjà traité. Consultez son rendez-vous dans le calendrier.')
    if actor['role']!='admin' and row['owner_id'] not in (None,actor['id']):
        raise HTTPException(409, 'Ce suivi est pris en charge par un autre agent.')


def prepare(db, actor, identifier, campaign_id, request_id):
    # Match calendar, qualification and callback lock ordering: actor ->
    # campaign -> request -> canonical contact -> queue/follow-up.
    row = inbound.followup(db, actor, identifier)
    eligible_followup(row, actor)
    campaign = campaigns.access(db, actor, campaign_id)
    query(db,'SELECT pg_advisory_xact_lock(:key)',key=int.from_bytes(request_id.bytes[:8],'big',signed=True))
    query(db, "INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,'{}') ON CONFLICT(phone) DO NOTHING",
        id=uuid4(),phone=row['caller_number'])
    contact = query(db,'SELECT * FROM staging.contacts WHERE phone=:phone FOR UPDATE',phone=row['caller_number']).mappings().one()
    row = inbound.followup(db, actor, identifier, lock=True)
    eligible_followup(row, actor)
    digest = inbound.fingerprint({'campaign_id':str(campaign_id)})
    old = inbound.replay(db,'inbound_followup_events',actor,request_id,identifier,digest,'followup_id')
    if contact['do_not_contact'] or contact['non_interested']:
        raise HTTPException(409, 'Un administrateur doit réactiver ce contact avant de prendre rendez-vous.')
    contact_id = contact['id']
    if old is None:
        campaigns.enroll(db,actor,campaign_id,[contact_id],None,request_id)
        inbound.record_event(db,identifier,'followup.updated',{'reason':'qualification.opened','result':{'contact_id':str(contact_id)},'campaign_id':str(campaign_id)},
            actor=actor['id'],request_id=request_id,digest=digest)
    card = campaigns.contact_access(db,campaign_id,contact_id)
    return {'campaign_id':str(campaign_id),'contact_id':str(contact_id),'membership_version':card['version'],
            'timezone':campaign['timezone'],'source_followup_id':str(identifier),'source_followup_version':row['version'],
            'qualification_schema':SCHEMA,'qualification':contact_snapshot(db,campaign_id,contact_id),'booker_name':actor['display_name']}


def prepare_call(db, actor, identifier, campaign_id, request_id):
    row=call_source(db,actor,identifier)
    if not row['caller_number']:
        raise HTTPException(409,'Cet appelant ne possède pas de numéro identifiable.')
    campaign=campaigns.access(db,actor,campaign_id)
    body={'action':'contact.inbound_qualification_opened','call_id':str(identifier)}
    previous=campaigns.replay(db,actor,campaign_id,request_id,body)
    query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,'{}') ON CONFLICT(phone) DO NOTHING",id=uuid4(),phone=row['caller_number'])
    contact=query(db,'SELECT * FROM staging.contacts WHERE phone=:phone FOR UPDATE',phone=row['caller_number']).mappings().one()
    if contact['do_not_contact'] or contact['non_interested']:
        raise HTTPException(409,'Un administrateur doit réactiver ce contact avant de prendre rendez-vous.')
    if previous is None:
        campaigns.enroll(db,actor,campaign_id,[contact['id']],None,uuid5(request_id,'incoming-call-enrollment'))
        campaigns.event(db,actor,campaign_id,body['action'],{'call_id':str(identifier)},contact_id=contact['id'],request_id=request_id,request_hash=campaigns.fingerprint(body))
    card=campaigns.contact_access(db,campaign_id,contact['id'])
    return {'campaign_id':str(campaign_id),'contact_id':str(contact['id']),'membership_version':card['version'],'timezone':campaign['timezone'],
            'qualification_schema':SCHEMA,'qualification':contact_snapshot(db,campaign_id,contact['id']),'booker_name':actor['display_name']}


def finish(db, actor, row, appointment_id):
    query(db, '''UPDATE staging.inbound_followups SET stage='handled',owner_id=:actor,callback_at=NULL,
        callback_timezone=NULL,closed_at=clock_timestamp(),version=version+1,updated_at=clock_timestamp() WHERE id=:id''',actor=actor['id'],id=row['id'])
    inbound.record_event(db,row['id'],'followup.updated',{'reason':'appointment.booked','before':{'stage':row['stage']},'appointment_id':str(appointment_id),'after':{'stage':'handled'}},actor=actor['id'])

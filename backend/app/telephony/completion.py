"""Durable call-to-CRM completion, outside webhook intent-lock transactions."""
from uuid import UUID

from app.identity.service import query
from app.campaigns import service as campaigns
from app.callbacks import service as callbacks
from app.telephony import service


def settle(db,identifier):
    lookup=query(db,'SELECT actor_id,campaign_id,contact_id,callback_id FROM staging.voice_intents WHERE id=:id',id=identifier).mappings().first()
    if lookup is None:return 'missing'
    actor=query(db,'SELECT * FROM staging.identity_users WHERE id=:id FOR UPDATE',id=lookup['actor_id']).mappings().one()
    hold=query(db,'''SELECT mode,lease_until>clock_timestamp() AS lease_alive FROM staging.voice_dialer_sessions
        WHERE actor_id=:id FOR UPDATE''',id=actor['id']).mappings().first()
    if hold and hold['mode']=='booking':
        if hold['lease_alive']:return 'waiting'
        # A closed/reloaded browser must not strand the completion outbox.
        query(db,'''UPDATE staging.voice_dialer_sessions SET mode='paused',hold_token=NULL,resume_after_hold=false,
            generation=generation+1,updated_at=clock_timestamp() WHERE actor_id=:id''',id=actor['id'])
    campaign=None
    if lookup['campaign_id']:
        campaign=query(db,'SELECT * FROM staging.campaigns WHERE id=:id FOR SHARE',id=lookup['campaign_id']).mappings().one()
    contact=None
    if lookup['contact_id']:
        contact=query(db,'SELECT * FROM staging.contacts WHERE id=:id FOR UPDATE',id=lookup['contact_id']).mappings().one()
    callback=None
    if lookup['callback_id']:
        callback=query(db,'SELECT * FROM staging.callbacks WHERE id=:id FOR UPDATE',id=lookup['callback_id']).mappings().first()
    row=query(db,'SELECT * FROM staging.voice_intents WHERE id=:id FOR UPDATE',id=identifier).mappings().one()
    job=query(db,'''SELECT *,next_attempt_at<=clock_timestamp() AS due FROM staging.voice_completion_jobs
        WHERE intent_id=:id FOR UPDATE''',id=identifier).mappings().first()
    if not job or job['completed_at'] or not job['due'] or row['state']!='finished':return 'waiting'
    if row['settled_at'] and row['settled_outcome_rank']>=row['outcome_rank']:
        query(db,'UPDATE staging.voice_completion_jobs SET completed_at=clock_timestamp(),last_error=false WHERE intent_id=:id',id=identifier)
        return 'already_settled'
    changed_version=row['settled_membership_version']
    if campaign and contact:
        card=query(db,'''SELECT m.*,s.kind AS stage_kind,s.name AS stage_name FROM staging.campaign_contacts m
            JOIN staging.campaign_stages s ON s.id=m.stage_id WHERE m.campaign_id=:campaign AND m.contact_id=:contact
            FOR UPDATE OF m''',campaign=campaign['id'],contact=contact['id']).mappings().first()
        expected=row['settled_membership_version'] if row['settled_membership_version'] is not None else row['membership_version']
        # Human changes, appointments, restrictions and newly scheduled callbacks
        # win over delayed provider events. Never overwrite a newer CRM decision.
        pending=query(db,"""SELECT 1 FROM staging.callbacks WHERE contact_id=:id AND status='scheduled'
            AND (id IS DISTINCT FROM CAST(:callback AS uuid) OR version IS DISTINCT FROM CAST(:version AS integer))""",
                      id=contact['id'],callback=row['callback_id'],version=row['callback_version']).first()
        if (card and card['is_active'] and card['version']==expected and not contact['do_not_contact']
                and not contact['non_interested'] and card['stage_kind'] not in {'appointment','non_interested','do_not_contact'}
                and not pending):
            kind='no_answer' if row['outcome'] in {'no-answer','busy'} else 'other'
            target=query(db,'SELECT id,name FROM staging.campaign_stages WHERE campaign_id=:campaign AND kind=:kind AND is_active',
                         campaign=campaign['id'],kind=kind).mappings().first()
            if target:
                changed=query(db,'''UPDATE staging.campaign_contacts SET stage_id=:stage,queue_position=DEFAULT,
                    version=version+1,updated_at=clock_timestamp() WHERE campaign_id=:campaign AND contact_id=:contact RETURNING version''',
                    stage=target['id'],campaign=campaign['id'],contact=contact['id']).scalar_one()
                changed_version=changed
                if card['stage_id']!=target['id']:
                    campaigns.event(db,actor,campaign['id'],'call.pipeline_updated',dict(intent_id=str(identifier),
                        outcome=row['outcome'],stage_id=str(target['id']),stage_name=target['name'],previous_stage_name=card['stage_name']),contact['id'])
        if row['settled_at'] is None:
            campaigns.event(db,actor,campaign['id'],'call.finished',dict(intent_id=str(identifier),
                outcome=row['outcome'],caller_number=row['caller_number'],destination=row['destination']),contact['id'])
    # A reservation or failed browser setup is not a completed callback. A
    # trusted child leg and terminal provider result prove the attempted call.
    if (callback and callback['status']=='scheduled' and callback['version']==row['callback_version']
            and callback['owner_id']==row['actor_id'] and row['child_call_sid']):
        query(db,'''UPDATE staging.callbacks SET status='completed',version=version+1,updated_at=clock_timestamp()
            WHERE id=:id''',id=callback['id'])
        callbacks.record(db,actor,callback['id'],'callback.called',dict(intent_id=str(identifier),
            outcome=row['outcome'],before=callbacks.snapshot(callback),after={**callbacks.snapshot(callback),'status':'completed'}))
    query(db,'''UPDATE staging.voice_intents SET settled_at=coalesce(settled_at,clock_timestamp()),
        settled_outcome_rank=outcome_rank,settled_membership_version=:version WHERE id=:id''',id=identifier,version=changed_version)
    query(db,'''UPDATE staging.voice_completion_jobs SET completed_at=clock_timestamp(),
        attempts=attempts+1,last_error=false WHERE intent_id=:id''',id=identifier)
    service.event(db,identifier,'crm.settled',{'outcome_rank':row['outcome_rank']})
    return 'settled'


def settle_actor(db,actor_id):
    identifiers=query(db,'''SELECT j.intent_id FROM staging.voice_completion_jobs j JOIN staging.voice_intents i ON i.id=j.intent_id
        WHERE i.actor_id=:actor AND j.completed_at IS NULL AND j.next_attempt_at<=clock_timestamp()
        ORDER BY i.created_at,i.id LIMIT 1''',actor=actor_id).scalars().all()
    for identifier in identifiers:settle(db,identifier)


def process_once(engine,profile):
    if profile is None:return 0
    with engine.begin() as db:
        # Backfill outcomes delivered while the compatibility image was active.
        query(db,'''INSERT INTO staging.voice_completion_jobs(intent_id)
            SELECT id FROM staging.voice_intents WHERE state='finished' AND settled_at IS NULL AND account_sid=:account
            ON CONFLICT DO NOTHING''',account=profile.account_sid)
        identifiers=query(db,'''SELECT j.intent_id FROM staging.voice_completion_jobs j JOIN staging.voice_intents i ON i.id=j.intent_id
            WHERE j.completed_at IS NULL AND j.next_attempt_at<=clock_timestamp() AND i.account_sid=:account
            ORDER BY j.next_attempt_at,j.intent_id LIMIT 20''',account=profile.account_sid).scalars().all()
    completed=0
    for identifier in identifiers:
        try:
            with engine.begin() as db:
                if settle(db,identifier)=='settled':completed+=1
        except Exception:
            with engine.begin() as db:
                query(db,'''UPDATE staging.voice_completion_jobs SET attempts=attempts+1,last_error=true,
                    next_attempt_at=clock_timestamp()+interval '15 seconds' WHERE intent_id=:id AND completed_at IS NULL''',id=identifier)
    return completed

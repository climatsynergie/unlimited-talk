"""One durable, browser-bound automatic controller per agent."""
from uuid import UUID
from itertools import chain

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.identity.service import query,audit
from app.campaigns import service as campaigns
from app.telephony import service,completion,dialer_policy as policy


def get(db,actor):
    row=query(db,'''SELECT *,lease_until>clock_timestamp() AS lease_alive FROM staging.voice_dialer_sessions
        WHERE actor_id=:id FOR UPDATE''',id=actor['id']).mappings().first()
    return row


def public(row):
    if row is None:return {'mode':'stopped','generation':0,'campaign_id':None,'browser_id':None,'owned_session':False}
    return {key: str(row[key]) if key in {'campaign_id','browser_id','hold_token'} and row[key] is not None else row[key]
            for key in ('mode','generation','campaign_id','browser_id','hold_token')}


def cancel_reserved(db,actor,generation):
    rows=query(db,'''SELECT id FROM staging.voice_intents WHERE actor_id=:actor
        AND dialer_generation=:generation AND state='reserved' FOR UPDATE''',actor=actor['id'],generation=generation).scalars().all()
    for identifier in rows:
        query(db,'''UPDATE staging.voice_intents SET state='cancelled',finished_at=clock_timestamp(),settled_at=clock_timestamp()
            WHERE id=:id''',id=identifier)
        service.event(db,identifier,'dialer.cancelled_before_authorization',{})


def control(db,actor,browser_id,action,campaign_id=None,generation=None,hold_token=None):
    row=get(db,actor)
    if action=='hold' and row is None:
        if campaign_id is None or hold_token is None:raise HTTPException(400,'Campagne et saisie de rendez-vous requises.')
        campaigns.access(db,actor,campaign_id)
        row=query(db,'''INSERT INTO staging.voice_dialer_sessions(actor_id,session_hash,browser_id,campaign_id,mode,lease_until,hold_token)
            VALUES (:actor,:session,:browser,:campaign,'booking',clock_timestamp()+interval '90 seconds',:hold) RETURNING *''',
            actor=actor['id'],session=actor['session_hash'],browser=browser_id,campaign=campaign_id,hold=hold_token).mappings().one()
        audit(db,actor['id'],'dialer.hold',campaign_id)
        return public(row)
    if action=='start':
        if campaign_id is None:raise HTTPException(400,'Choisissez une campagne.')
        campaigns.access(db,actor,campaign_id)
        config=policy.settings(db,campaign_id)
        if not config or not config['enabled'] or not config['default_number_id']:
            raise HTTPException(409,'Un administrateur doit choisir le numéro émetteur de cette campagne.')
        if row and row['mode']=='running' and row['lease_alive'] and (row['browser_id']!=browser_id or row['session_hash']!=actor['session_hash']):
            raise HTTPException(409,'Le composeur est déjà actif dans un autre navigateur.')
        active=query(db,'''SELECT * FROM staging.voice_intents WHERE actor_id=:id
            AND state IN ('reserved','authorized','ringing','answered')
            AND (state<>'reserved' OR expires_at>clock_timestamp()) LIMIT 1''',id=actor['id']).mappings().first()
        if active and (active['dialer_browser_id']!=browser_id or active['session_hash']!=actor['session_hash']):
            raise HTTPException(409,'Terminez ou vérifiez votre appel actuel avant de démarrer le composeur.')
        if row:
            if row['mode']=='running' and row['lease_alive'] and row['campaign_id']==campaign_id and row['browser_id']==browser_id and row['session_hash']==actor['session_hash']:
                return public(row)
            cancel_reserved(db,actor,row['generation'])
        row=query(db,'''INSERT INTO staging.voice_dialer_sessions(actor_id,session_hash,browser_id,campaign_id,mode,lease_until)
            VALUES (:actor,:session,:browser,:campaign,'running',clock_timestamp()+interval '90 seconds')
            ON CONFLICT(actor_id) DO UPDATE SET session_hash=excluded.session_hash,browser_id=excluded.browser_id,
                campaign_id=excluded.campaign_id,mode='running',generation=voice_dialer_sessions.generation+1,
                lease_until=excluded.lease_until,hold_token=NULL,resume_after_hold=false,updated_at=clock_timestamp()
            RETURNING *''',actor=actor['id'],session=actor['session_hash'],browser=browser_id,campaign=campaign_id).mappings().one()
    else:
        if not row or row['generation']!=generation:
            raise HTTPException(409,'Le composeur a changé. Actualisez son état avant de continuer.')
        same_browser=row['browser_id']==browser_id and row['session_hash']==actor['session_hash']
        if not same_browser:
            if action!='hold' or (row['mode']=='running' and row['lease_alive']):
                raise HTTPException(409,'Le composeur est contrôlé par un autre navigateur.')
            query(db,'UPDATE staging.voice_dialer_sessions SET browser_id=:browser,session_hash=:session WHERE actor_id=:actor',
                  browser=browser_id,session=actor['session_hash'],actor=actor['id'])
        if action=='release':
            if row['mode']!='booking' or row['hold_token']!=hold_token:
                raise HTTPException(409,'Cette saisie de rendez-vous ne contrôle plus le composeur.')
            mode='running' if row['resume_after_hold'] else 'paused'
            hold_token=None
            resume=False
        elif action=='hold':
            if hold_token is None:raise HTTPException(400,'Identifiant de saisie requis.')
            if row['mode']=='booking' and row['hold_token']==hold_token:return public(row)
            mode='booking'; resume=row['mode']=='running' and same_browser
        elif action in {'pause','stop'}:
            mode='paused' if action=='pause' else 'stopped'; hold_token=None; resume=False
        else:raise HTTPException(400,'Action du composeur invalide.')
        cancel_reserved(db,actor,row['generation'])
        row=query(db,'''UPDATE staging.voice_dialer_sessions SET mode=:mode,generation=generation+1,
            hold_token=:hold,resume_after_hold=:resume,lease_until=clock_timestamp()+interval '90 seconds',updated_at=clock_timestamp()
            WHERE actor_id=:actor RETURNING *''',actor=actor['id'],mode=mode,hold=hold_token,resume=resume).mappings().one()
    audit(db,actor['id'],'dialer.'+action,campaign_id or row['campaign_id'])
    return public(row)


ELIGIBLE = '''
    NOT c.do_not_contact AND NOT c.non_interested AND ca.is_active AND m.is_active
    AND NOT EXISTS(SELECT 1 FROM staging.appointments ap WHERE ap.contact_id=c.id AND ap.status='booked' AND ap.ends_at>clock_timestamp())
    AND (:admin OR EXISTS(SELECT 1 FROM staging.campaign_agents ag WHERE ag.campaign_id=m.campaign_id
        AND ag.user_id=:actor AND ag.is_active))
    AND EXISTS(SELECT 1 FROM staging.voice_campaign_settings cfg WHERE cfg.campaign_id=m.campaign_id AND cfg.enabled)
    AND NOT EXISTS(SELECT 1 FROM staging.voice_intents i WHERE i.account_sid=:account AND i.destination=c.phone
        AND i.state IN ('reserved','authorized','ringing','answered') AND (i.state<>'reserved' OR i.expires_at>clock_timestamp()))
    AND NOT EXISTS(SELECT 1 FROM staging.voice_intents i WHERE i.account_sid=:account AND i.destination=c.phone
        AND i.consumed_at>clock_timestamp()-interval '2 hours')
    AND (SELECT count(*) FROM staging.voice_intents i WHERE i.account_sid=:account AND i.destination=c.phone
        AND i.consumed_at >= (date_trunc('day',clock_timestamp() AT TIME ZONE coalesce(
            (SELECT first.attempt_timezone FROM staging.voice_intents first WHERE first.account_sid=:account
                AND first.destination=c.phone ORDER BY first.created_at,first.id LIMIT 1),ca.timezone))
            AT TIME ZONE coalesce((SELECT first.attempt_timezone FROM staging.voice_intents first
                WHERE first.account_sid=:account AND first.destination=c.phone ORDER BY first.created_at,first.id LIMIT 1),ca.timezone))) < 2
'''


def candidates(db,values,campaign_id=None):
    """Keyset batches retain priority without starving rows after the first 100."""
    after=None
    after_id=None
    while True:
        if campaign_id is None:
            statement='''SELECT cb.campaign_id,c.id AS contact_id,c.phone,
                cb.due_at AS candidate_order,cb.id AS candidate_key FROM staging.callbacks cb
                JOIN staging.contacts c ON c.id=cb.contact_id JOIN staging.campaigns ca ON ca.id=cb.campaign_id
                JOIN staging.campaign_contacts m ON m.campaign_id=cb.campaign_id AND m.contact_id=cb.contact_id
                WHERE cb.owner_id=:actor AND cb.status='scheduled' AND cb.due_at<=clock_timestamp()
                AND (CAST(:after AS timestamptz) IS NULL OR (cb.due_at,cb.id)>(CAST(:after AS timestamptz),CAST(:after_id AS uuid)))
                AND '''+ELIGIBLE+''' ORDER BY cb.due_at,cb.id LIMIT 100'''
        else:
            statement='''SELECT m.campaign_id,c.id AS contact_id,c.phone,
                m.queue_position AS candidate_order,c.id AS candidate_key FROM staging.campaign_contacts m
                JOIN staging.contacts c ON c.id=m.contact_id JOIN staging.campaigns ca ON ca.id=m.campaign_id
                JOIN staging.campaign_stages s ON s.id=m.stage_id
                WHERE m.campaign_id=:campaign AND s.kind IN ('new','no_answer','other','custom')
                AND NOT EXISTS(SELECT 1 FROM staging.callbacks cb WHERE cb.contact_id=c.id AND cb.status='scheduled')
                AND (CAST(:after AS bigint) IS NULL OR (m.queue_position,c.id)>(CAST(:after AS bigint),CAST(:after_id AS uuid)))
                AND '''+ELIGIBLE+''' ORDER BY m.queue_position,c.id LIMIT 100'''
        page=query(db,statement,**values,campaign=campaign_id,after=after,after_id=after_id).mappings().all()
        if not page:return
        yield from page
        after,after_id=page[-1]['candidate_order'],page[-1]['candidate_key']
        if len(page)<100:return


def next_call(db,actor,profile,browser_id,generation,identifier):
    completion.settle_actor(db,actor['id'])
    row=get(db,actor)
    if (not row or row['browser_id']!=browser_id or row['session_hash']!=actor['session_hash']
            or row['generation']!=generation):
        raise HTTPException(409,'Le composeur appartient à une autre session ou a changé.')
    if row['mode']!='running':return {'idle':row['mode'],'dialer':public(row)}
    if not row['lease_alive']:
        state=control(db,actor,browser_id,'pause',generation=generation)
        return {'idle':'presence_expired','dialer':state}
    query(db,'''UPDATE staging.voice_dialer_sessions SET lease_until=clock_timestamp()+interval '90 seconds',updated_at=clock_timestamp()
        WHERE actor_id=:actor''',actor=actor['id'])
    previous=query(db,'SELECT * FROM staging.voice_intents WHERE id=:id',id=identifier).mappings().first()
    if previous:
        if (previous['actor_id']!=actor['id'] or previous['session_hash']!=actor['session_hash']
                or previous['dialer_browser_id']!=browser_id or previous['dialer_generation']!=generation
                or previous['state']!='reserved'):
            raise HTTPException(409,'Cette demande d’appel ne peut pas être rejouée.')
        reserved=service.reserve(db,actor,identifier,profile,previous['destination'],campaign_id=previous['campaign_id'],automatic=row)
        return {'reserved':reserved,'dialer':public(row)}
    active=query(db,'''SELECT id FROM staging.voice_intents WHERE actor_id=:actor
        AND state IN ('reserved','authorized','ringing','answered')
        AND (state<>'reserved' OR expires_at>clock_timestamp()) LIMIT 1''',actor=actor['id']).first()
    if active:return {'idle':'active_call','dialer':public(row)}
    pending=query(db,'''SELECT 1 FROM staging.voice_completion_jobs j JOIN staging.voice_intents i ON i.id=j.intent_id
        WHERE i.actor_id=:actor AND j.completed_at IS NULL LIMIT 1''',actor=actor['id']).first()
    if pending:return {'idle':'settling','dialer':public(row)}
    values=dict(actor=actor['id'],admin=actor['role']=='admin',account=profile.account_sid)
    reason='empty'
    for candidate in chain(candidates(db,values),candidates(db,values,row['campaign_id'])):
        try:
            with db.begin_nested():
                campaigns.access(db,actor,candidate['campaign_id'])
                available=query(db,'SELECT id FROM staging.contacts WHERE id=:id FOR UPDATE SKIP LOCKED',id=candidate['contact_id']).first()
                if available is None:continue
                reserved=service.reserve(db,actor,identifier,profile,candidate['phone'],campaign_id=candidate['campaign_id'],automatic=row)
                query(db,'UPDATE staging.identity_sessions SET last_seen_at=clock_timestamp() WHERE token_hash=:session',session=actor['session_hash'])
                return {'reserved':reserved,'dialer':public(row)}
        except HTTPException as error:
            if error.status_code not in {400,403,404,409}:raise
            reason='policy'
        except IntegrityError:
            reason='claimed'
    return {'idle':reason,'dialer':public(row)}

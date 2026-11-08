"""Explicit English hand-off, preserving contact identity and campaign history."""
from uuid import uuid4
from fastapi import HTTPException
from app.identity.service import query,audit
from app.campaigns import service


DESTINATION='campaign.english_destination'


def destination(db,actor):
    # Serializes creation and stage positions across referrals and API replicas.
    query(db,'SELECT pg_advisory_xact_lock(7419201201)')
    row=query(db,'''SELECT c.* FROM staging.campaign_events e JOIN staging.campaigns c ON c.id=e.campaign_id
        WHERE e.action=:action ORDER BY e.id LIMIT 1''',action=DESTINATION).mappings().first()
    if row:
        if not row['is_active']:raise HTTPException(409,'La campagne « Contacts anglophones » est archivée. Un administrateur doit la réactiver pour recevoir ces contacts.')
        return row
    name='Contacts anglophones'
    existing=query(db,'SELECT * FROM staging.campaigns WHERE lower(name)=lower(:name)',name=name).mappings().first()
    if existing:
        if not existing['is_active']:raise HTTPException(409,'La campagne « Contacts anglophones » est archivée. Un administrateur doit la réactiver.')
        service.event(db,actor,existing['id'],DESTINATION,{'language':'en'})
        return existing
    identifier=uuid4()
    row=query(db,'''INSERT INTO staging.campaigns(id,name,timezone,created_by)
        VALUES (:id,:name,'America/Toronto',:actor) RETURNING *''',id=identifier,name=name,actor=actor['id']).mappings().one()
    for position,(label,kind,color) in enumerate(service.DEFAULT_STAGES):
        query(db,'''INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position)
            VALUES (:id,:campaign,:name,:kind,:color,:position)''',id=uuid4(),campaign=identifier,name=label,kind=kind,color=color,position=position)
    service.event(db,actor,identifier,DESTINATION,{'language':'en'})
    audit(db,actor['id'],'campaign.english_created',identifier)
    return row


def refer(db,actor,campaign_id,contact_id,version,request_id,source_intent_id=None):
    body=dict(action='contact.english_referred',contact=str(contact_id),version=version,
              source_intent_id=str(source_intent_id) if source_intent_id else None)
    previous=service.replay(db,actor,campaign_id,request_id,body)
    if previous is not None:return previous
    # Match the caller's normal contact-before-memberships ordering. Creation
    # above is done after this lock, consistently for every referral.
    contact=query(db,'SELECT * FROM staging.contacts WHERE id=:id FOR UPDATE',id=contact_id).mappings().first()
    if contact is None:raise HTTPException(404,'Contact introuvable.')
    card=service.contact_access(db,campaign_id,contact_id)
    if contact['do_not_contact'] or contact['non_interested']:
        raise HTTPException(409,'Ce contact possède une restriction. Le transfert ne réactive pas les contacts bloqués.')
    if source_intent_id:
        source=query(db,'SELECT * FROM staging.voice_intents WHERE id=:id',id=source_intent_id).mappings().first()
        if not source or any(source[key]!=value for key,value in [('actor_id',actor['id']),('campaign_id',campaign_id),('contact_id',contact_id)]):
            raise HTTPException(403,'Cet appel ne correspond pas à cette fiche ou à votre compte.')
    else:source=None
    if card['version']!=version and not (source and source['state']=='finished'
            and source['membership_version']==version and source['settled_membership_version']==card['version']):
        raise HTTPException(409,'La fiche a changé. Actualisez-la avant de confirmer le transfert.',headers={'X-Error-Code':'stale_campaign_contact'})
    if query(db,"SELECT 1 FROM staging.appointments WHERE contact_id=:id AND status='booked' AND ends_at>clock_timestamp() LIMIT 1",id=contact_id).first():
        raise HTTPException(409,'Conservez le rendez-vous ou le rappel existant. Modifiez son attribution avant de transférer ce contact.')
    if query(db,"SELECT 1 FROM staging.callbacks WHERE contact_id=:id AND status='scheduled' LIMIT 1",id=contact_id).first():
        raise HTTPException(409,'Ce contact possède un rappel programmé, même s’il est déjà arrivé à échéance. Son responsable ou un administrateur doit le clôturer avant le transfert.')
    target=destination(db,actor)
    # Reuse the source's known caller for a newly configured destination; an
    # administrator's existing choices always win, including disabled calling.
    query(db,'''INSERT INTO staging.voice_campaign_settings(campaign_id,enabled,default_number_id,updated_by)
        SELECT :target,enabled,default_number_id,:actor FROM staging.voice_campaign_settings WHERE campaign_id=:source
        ON CONFLICT(campaign_id) DO NOTHING''',target=target['id'],source=campaign_id,actor=actor['id'])
    query(db,"UPDATE staging.contacts SET profile=jsonb_set(profile,'{preferred_language}','\"en\"'),updated_at=clock_timestamp() WHERE id=:id",id=contact_id)
    stage=card['stage_id']
    if campaign_id!=target['id']:
        stage=query(db,'''SELECT s.id FROM staging.campaign_events e JOIN staging.campaign_stages s
            ON s.id=CAST(e.details->>'stage_id' AS uuid) AND s.campaign_id=e.campaign_id AND s.is_active
            WHERE e.campaign_id=:id AND e.action='english.stage_defined' ORDER BY e.id DESC LIMIT 1''',id=campaign_id).scalar_one_or_none()
        if stage is None:
            stage=query(db,"SELECT id FROM staging.campaign_stages WHERE campaign_id=:id AND lower(name)='anglais' AND kind='custom' AND is_active",id=campaign_id).scalar_one_or_none()
            if stage is None:
                stage=uuid4()
                occupied=query(db,"SELECT 1 FROM staging.campaign_stages WHERE campaign_id=:id AND lower(name)='anglais'",id=campaign_id).first()
                query(db,'''INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position)
                    SELECT :stage,:id,:name,'custom','blue',coalesce(max(position),-1)+1 FROM staging.campaign_stages WHERE campaign_id=:id''',stage=stage,id=campaign_id,name='Anglais · transféré' if occupied else 'Anglais')
            service.event(db,actor,campaign_id,'english.stage_defined',{'stage_id':str(stage)})
        target_stage=query(db,"SELECT id FROM staging.campaign_stages WHERE campaign_id=:id AND kind='new' AND is_active",id=target['id']).scalar_one_or_none()
        if target_stage is None:raise HTTPException(409,'Un administrateur doit restaurer l’étape « À appeler » de la campagne anglophone.')
        added=query(db,'''INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id)
            VALUES (:campaign,:contact,:stage) ON CONFLICT(campaign_id,contact_id) DO NOTHING RETURNING contact_id''',campaign=target['id'],contact=contact_id,stage=target_stage).first()
        existing=query(db,'SELECT is_active FROM staging.campaign_contacts WHERE campaign_id=:campaign AND contact_id=:contact',campaign=target['id'],contact=contact_id).scalar_one()
        if not existing:raise HTTPException(409,'Ce contact a été retiré de la campagne anglophone. Un administrateur doit rétablir son attribution.')
        if added:service.event(db,actor,target['id'],'contact.english_received',{'origin_campaign_id':str(campaign_id)},contact_id)
    changed=query(db,'''UPDATE staging.campaign_contacts SET stage_id=:stage,version=version+1,
        queue_position=DEFAULT,updated_at=clock_timestamp() WHERE campaign_id=:campaign AND contact_id=:contact RETURNING version''',stage=stage,campaign=campaign_id,contact=contact_id).scalar_one()
    result=dict(destination_campaign_id=str(target['id']),destination_campaign_name=target['name'],version=changed)
    service.event(db,actor,campaign_id,'contact.english_referred',result,contact_id,request_id,service.fingerprint(body))
    audit(db,actor['id'],'contact.english_referred',contact_id)
    return result

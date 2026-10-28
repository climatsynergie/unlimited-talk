"""Campaign access, optimistic card moves and global contact restrictions."""
import hashlib
import json
import uuid
from fastapi import HTTPException
from app.identity.service import query, audit, authenticate
from app.callbacks.service import cancel_for_contact

DEFAULT_STAGES = [
    ('À appeler','new','violet'),('Pas de réponse','no_answer','amber'),
    ('À rappeler','callback','blue'),('Autre','other','slate'),
    ('RDV booké','appointment','green'),('Non intéressé','non_interested','rose'),
    ('Ne pas contacter','do_not_contact','rose'),
]


def administrator(user):
    if user['role'] != 'admin':
        raise HTTPException(403,'Accès administrateur requis')


def access(db, user, campaign_id, *, edit=False, allow_archived=False):
    row=query(db,'SELECT * FROM staging.campaigns WHERE id=:id'+(' FOR UPDATE' if edit else ' FOR SHARE'),id=campaign_id).mappings().first()
    if row is None:
        raise HTTPException(404,'Campagne introuvable.')
    if user['role']!='admin':
        assigned=query(db,'''SELECT 1 FROM staging.campaign_agents WHERE campaign_id=:id
            AND user_id=:user AND is_active''',id=campaign_id,user=user['id']).first()
        if not assigned or not row['is_active']:
            raise HTTPException(403,'Cette campagne ne vous est pas attribuée.')
    if not row['is_active'] and not allow_archived:
        raise HTTPException(409,'Cette campagne est archivée.')
    return row


def event(db,user,campaign_id,action,details=None,contact_id=None,request_id=None,request_hash=None):
    query(db,'''INSERT INTO staging.campaign_events(request_id,request_hash,campaign_id,contact_id,actor_id,action,details)
        VALUES (:request,:hash,:campaign,:contact,:actor,:action,CAST(:details AS jsonb))''',
        request=request_id,hash=request_hash,campaign=campaign_id,contact=contact_id,actor=user['id'],
        action=action,details=json.dumps(details or {}))


def fingerprint(body):
    return hashlib.sha256(json.dumps(body,sort_keys=True,default=str).encode()).hexdigest()


def replay(db,user,campaign,request_id,body):
    # Serialize the same request across campaigns too; the idempotency record is global.
    query(db,'SELECT pg_advisory_xact_lock(:key)',key=int.from_bytes(request_id.bytes[:8],'big',signed=True))
    previous=query(db,'SELECT * FROM staging.campaign_events WHERE request_id=:id',id=request_id).mappings().first()
    if previous:
        if previous['actor_id']!=user['id'] or previous['campaign_id']!=campaign or previous['request_hash']!=fingerprint(body):
            raise HTTPException(409,'Cet identifiant d’action a déjà été utilisé autrement.')
        return previous['details']
    return None


def stages(db,campaign_id):
    return query(db,'SELECT * FROM staging.campaign_stages WHERE campaign_id=:id AND is_active ORDER BY position',id=campaign_id).mappings().all()


def contact_access(db,campaign_id,contact_id):
    row=query(db,'''SELECT m.*,c.phone,c.profile,c.do_not_contact,c.non_interested,c.updated_at AS contact_updated_at FROM staging.campaign_contacts m
        JOIN staging.contacts c ON c.id=m.contact_id WHERE campaign_id=:campaign AND contact_id=:contact AND m.is_active''',
        campaign=campaign_id,contact=contact_id).mappings().first()
    if row is None:
        raise HTTPException(404,'Ce contact ne figure pas dans cette campagne.')
    return row


def move(db,user,campaign_id,contact_id,stage_id,version,request_id):
    body=dict(action='card.moved',contact=str(contact_id),stage=str(stage_id),version=version)
    previous=replay(db,user,campaign_id,request_id,body)
    if previous is not None:
        return previous
    # Lock the canonical contact before its memberships, including other campaigns.
    contact=query(db,'SELECT * FROM staging.contacts WHERE id=:id FOR UPDATE',id=contact_id).mappings().first()
    if contact is None:
        raise HTTPException(404,'Contact introuvable.')
    card=contact_access(db,campaign_id,contact_id)
    if card['version']!=version:
        raise HTTPException(409,'Cette fiche a changé. Actualisez le pipeline avant de la déplacer.')
    target=query(db,'SELECT * FROM staging.campaign_stages WHERE campaign_id=:campaign AND id=:id AND is_active',
        campaign=campaign_id,id=stage_id).mappings().first()
    if target is None:
        raise HTTPException(400,'Étape invalide pour cette campagne.')
    if contact['do_not_contact'] and target['kind']!='do_not_contact':
        raise HTTPException(409,'Ce contact est bloqué globalement. Un administrateur doit lever la restriction.')
    if contact['non_interested'] and target['kind'] not in {'non_interested','do_not_contact'}:
        raise HTTPException(409,'Ce contact est non intéressé dans toutes les campagnes. Un administrateur doit le réactiver.')
    if target['kind'] in {'non_interested','do_not_contact'}:
        flag=target['kind']
        cancel_for_contact(db,user,contact_id,flag)
        # Identifier chosen only from the fixed semantic allowlist above.
        query(db,'UPDATE staging.contacts SET '+flag+'=true,updated_at=now() WHERE id=:id',id=contact_id)
        rows=query(db,'''SELECT m.campaign_id,m.stage_id,m.version,s.id AS destination FROM staging.campaign_contacts m
            JOIN staging.campaign_stages s ON s.campaign_id=m.campaign_id AND s.kind=:kind
            WHERE m.contact_id=:contact AND m.is_active ORDER BY m.campaign_id FOR UPDATE OF m''',kind=flag,contact=contact_id).mappings().all()
        for row in rows:
            query(db,'''UPDATE staging.campaign_contacts SET stage_id=:stage,queue_position=DEFAULT,version=version+1,updated_at=now()
                WHERE campaign_id=:campaign AND contact_id=:contact''',campaign=row['campaign_id'],contact=contact_id,stage=row['destination'])
            if row['campaign_id']!=campaign_id:
                event(db,user,row['campaign_id'],'contact.restricted',{'kind':flag},contact_id)
    else:
        query(db,'''UPDATE staging.campaign_contacts SET stage_id=:stage,queue_position=DEFAULT,version=version+1,updated_at=now()
            WHERE campaign_id=:campaign AND contact_id=:contact''',campaign=campaign_id,contact=contact_id,stage=stage_id)
    origin=query(db,'SELECT name FROM staging.campaign_stages WHERE id=:id',id=card['stage_id']).scalar_one()
    result={'stage_id':str(stage_id),'stage_name':target['name'],'previous_stage_name':origin,'version':version+1,'global_restriction':target['kind'] if target['kind'] in {'non_interested','do_not_contact'} else None}
    event(db,user,campaign_id,'card.moved',result,contact_id,request_id,fingerprint(body))
    return result


def enroll(db,user,campaign_id,contact_ids,import_id,request_id):
    body=dict(action='contacts.enrolled',contacts=sorted(str(i) for i in contact_ids),import_id=str(import_id) if import_id else None)
    previous=replay(db,user,campaign_id,request_id,body)
    if previous is not None:
        return previous
    if import_id:
        job=query(db,'SELECT status FROM staging.contact_imports WHERE id=:id',id=import_id).scalar_one_or_none()
        if job!='completed':
            raise HTTPException(409,'Choisissez un import terminé.')
        selector='c.id IN (SELECT contact_id FROM staging.contact_import_rows WHERE import_id=:source AND contact_id IS NOT NULL)'
        values={'source':import_id}
    else:
        selector='c.id = ANY(CAST(:ids AS uuid[]))'
        values={'ids':[str(i) for i in contact_ids]}
    # One bounded SQL transaction handles an import without browser-side job loops.
    query(db,"SET LOCAL statement_timeout='15000ms'")
    if not import_id:
        count=query(db,'SELECT count(*) FROM staging.contacts c WHERE '+selector,**values).scalar_one()
        if count!=len(set(contact_ids)):
            raise HTTPException(400,'Un ou plusieurs contacts sont introuvables.')
    result_row=query(db,"""WITH candidates AS MATERIALIZED (
        SELECT c.id,s.id AS stage_id FROM staging.contacts c
        JOIN staging.campaign_stages s ON s.campaign_id=:campaign AND s.kind=
            CASE WHEN c.do_not_contact THEN 'do_not_contact' WHEN c.non_interested THEN 'non_interested' ELSE 'new' END
        WHERE """+selector+""" ORDER BY c.id FOR UPDATE OF c
    ), inserted AS (
        INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id,source_import_id)
        SELECT :campaign,id,stage_id,:import_id FROM candidates
        ON CONFLICT(campaign_id,contact_id) DO UPDATE SET is_active=true,
            stage_id=excluded.stage_id,queue_position=DEFAULT,version=campaign_contacts.version+1,updated_at=now()
            WHERE NOT campaign_contacts.is_active
        RETURNING contact_id,stage_id
    ), recorded AS (
        INSERT INTO staging.campaign_events(campaign_id,contact_id,actor_id,action,details)
        SELECT :campaign,contact_id,:actor,'contact.enrolled',jsonb_build_object('stage_id',stage_id,'source_import_id',CAST(:import_id AS uuid)) FROM inserted
    ) SELECT (SELECT count(*) FROM candidates) AS total,(SELECT count(*) FROM inserted) AS added""",
        campaign=campaign_id,actor=user['id'],import_id=import_id,**values).mappings().one()
    result={'added':result_row['added'],'existing':result_row['total']-result_row['added'],'total':result_row['total']}
    event(db,user,campaign_id,'contacts.enrolled',result,None,request_id,fingerprint(body))
    audit(db,user['id'],'campaign.contacts_enrolled',campaign_id)
    return result

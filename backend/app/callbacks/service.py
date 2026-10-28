"""Durable callback reservations and priority candidates, independent of Redis."""
import json
from fastapi import HTTPException
from app.identity.service import query,audit

SELECT='''SELECT cb.*,c.phone,c.profile,ca.name AS campaign_name,u.display_name AS owner_name,
    (cb.status='scheduled' AND cb.due_at<=clock_timestamp()) AS is_due,
    CASE WHEN c.do_not_contact OR c.non_interested THEN 'restricted'
         WHEN NOT u.is_active THEN 'inactive_owner'
         WHEN NOT ca.is_active THEN 'archived_campaign'
         WHEN NOT EXISTS(SELECT 1 FROM staging.campaign_contacts m WHERE m.campaign_id=cb.campaign_id AND m.contact_id=cb.contact_id AND m.is_active) THEN 'removed_contact'
         WHEN u.role!='admin' AND NOT EXISTS(SELECT 1 FROM staging.campaign_agents ag
             WHERE ag.campaign_id=cb.campaign_id AND ag.user_id=cb.owner_id AND ag.is_active) THEN 'unassigned'
         ELSE NULL END AS blocked_reason
    FROM staging.callbacks cb JOIN staging.contacts c ON c.id=cb.contact_id
    JOIN staging.campaigns ca ON ca.id=cb.campaign_id JOIN staging.identity_users u ON u.id=cb.owner_id'''


def get(db,user,identifier):
    row=query(db,SELECT+' WHERE cb.id=:id',id=identifier).mappings().first()
    if row is None:raise HTTPException(404,'Rappel introuvable.')
    if user['role']!='admin' and row['owner_id']!=user['id']:
        raise HTTPException(403,'Ce rappel appartient à un autre agent.')
    return dict(row)


def snapshot(row):
    return {k:row[k] for k in ('due_at','timezone','notes','status')}


def record(db,user,identifier,action,details):
    query(db,'''INSERT INTO staging.callback_events(callback_id,actor_id,action,details)
        VALUES (:id,:actor,:action,CAST(:details AS jsonb))''',id=identifier,actor=user['id'],action=action,details=json.dumps(details,default=str))
    audit(db,user['id'],action,identifier)


def cancel_for_contact(db,user,contact_id,reason,campaign_id=None):
    # Callers hold the canonical contact lock; every writer uses contact -> callback.
    rows=query(db,"SELECT * FROM staging.callbacks WHERE contact_id=:id AND status='scheduled' AND (CAST(:campaign AS uuid) IS NULL OR campaign_id=:campaign) ORDER BY id FOR UPDATE",id=contact_id,campaign=campaign_id).mappings().all()
    for row in rows:
        query(db,"UPDATE staging.callbacks SET status='cancelled',version=version+1,updated_at=clock_timestamp() WHERE id=:id",id=row['id'])
        after={**snapshot(row),'status':'cancelled'}
        record(db,user,row['id'],'callback.cancelled',{'before':snapshot(row),'after':after,'reason':reason})


def due_candidates(db,user,limit=20):
    """Read-only priority list for the future dialer, never a claim or a call.

    Dialer integration must atomically claim/lock the contact and recheck global
    suppression, agent availability, campaign hours and all attempt limits.
    Every pending callback reserves its contact across ordinary campaign queues.
    """
    rows=query(db,SELECT+''' WHERE cb.owner_id=:owner AND cb.status='scheduled'
        AND cb.due_at<=clock_timestamp() AND NOT c.do_not_contact AND NOT c.non_interested
        AND ca.is_active AND u.is_active AND EXISTS(SELECT 1 FROM staging.campaign_contacts m WHERE m.campaign_id=cb.campaign_id AND m.contact_id=cb.contact_id AND m.is_active) AND (u.role='admin' OR EXISTS(SELECT 1 FROM staging.campaign_agents ag
            WHERE ag.campaign_id=cb.campaign_id AND ag.user_id=cb.owner_id AND ag.is_active))
        ORDER BY cb.due_at,cb.id LIMIT :limit''',owner=user['id'],limit=min(max(limit,1),100)).mappings().all()
    return [dict(r) for r in rows]

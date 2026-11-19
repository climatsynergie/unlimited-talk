"""Explicit operator recovery for a completed import whose enrollment timed out.

Run inside the application's runtime environment. Dry run is the default. This
does not upload/split CSV objects, modify import history, or change application
code/configuration. Each <=500-source-row transaction retains the normal
enrollment semantics, source provenance, actor audit and immutable events.
Deterministic batch request IDs permit resuming an interrupted operator run.
"""
import argparse
import json
import time
import uuid

from app.campaigns import service
from app.database import make_engine
from app.identity.service import audit, query

BATCH_SIZE = 500


def inspect(engine, actor, campaign, source, source_hash, campaign_name):
    with engine.connect() as db:
        query(db, 'SET TRANSACTION READ ONLY')
        user = query(db, 'SELECT id,role,is_active FROM staging.identity_users WHERE id=:id', id=actor).mappings().one()
        if not user['is_active']:
            raise RuntimeError('Inactive operator account')
        service.administrator(user)
        row = query(db, 'SELECT name,is_active FROM staging.campaigns WHERE id=:id', id=campaign).mappings().one()
        if row['name'] != campaign_name or not row['is_active']:
            raise RuntimeError('Campaign identity/state mismatch')
        job = query(db, 'SELECT * FROM staging.contact_imports WHERE id=:id', id=source).mappings().one()
        if job['status'] != 'completed' or job['created_by'] != actor or job['source_sha256'] != source_hash:
            raise RuntimeError('Completed import owner/checksum mismatch')
        rows = query(db, '''SELECT count(*) AS rows,max(row_number) AS last_row,
            count(contact_id) AS valid_rows,count(DISTINCT contact_id) AS unique_contacts
            FROM staging.contact_import_rows WHERE import_id=:id''', id=source).mappings().one()
        if rows['rows'] != job['total'] or job['processed'] != job['total'] or not rows['unique_contacts']:
            raise RuntimeError('Incomplete import rows')
        counts = query(db, '''SELECT count(*) AS source_contacts,
            count(*) FILTER (WHERE m.is_active) AS active_memberships,
            count(*) FILTER (WHERE m.contact_id IS NULL) AS missing_memberships,
            count(*) FILTER (WHERE NOT m.is_active) AS inactive_memberships
            FROM (SELECT DISTINCT contact_id FROM staging.contact_import_rows
                  WHERE import_id=:source AND contact_id IS NOT NULL) r
            LEFT JOIN staging.campaign_contacts m ON m.contact_id=r.contact_id AND m.campaign_id=:campaign''',
            source=source, campaign=campaign).mappings().one()
        return {**dict(rows), **dict(counts), 'campaign': row['name'], 'invalid_rows': job['invalid']}


def run_batch(engine, actor, campaign, source, source_hash, campaign_name, lower, upper):
    if lower < 0 or upper <= lower or upper - lower > BATCH_SIZE:
        raise ValueError('Invalid bounded row interval')
    body = dict(action='contacts.import_batch_enrolled', import_id=str(source),
                source_sha256=source_hash, after_row=lower, through_row=upper)
    request_id = uuid.uuid5(campaign, 'import-enrollment-v1/' + service.fingerprint(body))
    with engine.begin() as db:
        query(db, "SET LOCAL lock_timeout='750ms'")
        user = query(db, 'SELECT * FROM staging.identity_users WHERE id=:id AND is_active FOR UPDATE', id=actor).mappings().one()
        service.administrator(user)
        target = service.access(db, user, campaign)
        if target['name'] != campaign_name:
            raise RuntimeError('Campaign identity changed')
        job = query(db, 'SELECT status,created_by,source_sha256 FROM staging.contact_imports WHERE id=:id FOR SHARE', id=source).mappings().one()
        if job['status'] != 'completed' or job['created_by'] != actor or job['source_sha256'] != source_hash:
            raise RuntimeError('Import identity/state changed')
        previous = service.replay(db, user, campaign, request_id, body)
        if previous is not None:
            return {**previous, 'replayed': True}
        kinds = set(query(db, 'SELECT kind FROM staging.campaign_stages WHERE campaign_id=:id', id=campaign).scalars())
        if not {'new', 'do_not_contact', 'non_interested'} <= kinds:
            raise RuntimeError('Required semantic stages missing')
        # Same canonical-contact lock order, conflict handling and immutable
        # history as service.enroll; only the source-row selector is bounded.
        query(db, "SET LOCAL statement_timeout='15000ms'")
        row = query(db, '''WITH candidates AS MATERIALIZED (
            SELECT c.id,s.id AS stage_id FROM staging.contacts c
            JOIN staging.campaign_stages s ON s.campaign_id=:campaign AND s.kind=
              CASE WHEN c.do_not_contact THEN 'do_not_contact' WHEN c.non_interested THEN 'non_interested' ELSE 'new' END
            WHERE c.id IN (SELECT contact_id FROM staging.contact_import_rows
              WHERE import_id=:source AND row_number>:lower AND row_number<=:upper AND contact_id IS NOT NULL)
            ORDER BY c.id FOR UPDATE OF c
        ), inserted AS (
            INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id,source_import_id)
            SELECT :campaign,id,stage_id,:source FROM candidates
            ON CONFLICT(campaign_id,contact_id) DO UPDATE SET is_active=true,
              stage_id=excluded.stage_id,queue_position=DEFAULT,
              version=campaign_contacts.version+1,updated_at=now()
              WHERE NOT campaign_contacts.is_active
            RETURNING contact_id,stage_id
        ), recorded AS (
            INSERT INTO staging.campaign_events(campaign_id,contact_id,actor_id,action,details)
            SELECT :campaign,contact_id,:actor,'contact.enrolled',
              jsonb_build_object('stage_id',stage_id,'source_import_id',CAST(:source AS uuid)) FROM inserted
        ) SELECT (SELECT count(*) FROM candidates) AS total,
                 (SELECT count(*) FROM inserted) AS added''',
            campaign=campaign, source=source, actor=actor, lower=lower, upper=upper).mappings().one()
        result = dict(total=row['total'], added=row['added'], existing=row['total']-row['added'],
                      import_id=str(source), after_row=lower, through_row=upper)
        service.event(db, user, campaign, body['action'], result, request_id=request_id,
                      request_hash=service.fingerprint(body))
        audit(db, actor, 'campaign.contacts_enrolled', campaign)
        return {**result, 'replayed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actor', type=uuid.UUID, required=True)
    parser.add_argument('--campaign', type=uuid.UUID, required=True)
    parser.add_argument('--import-id', type=uuid.UUID, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--campaign-name', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if len(args.source_sha256) != 64 or any(c not in '0123456789abcdef' for c in args.source_sha256):
        parser.error('Invalid source SHA256')
    engine = make_engine()
    values = (args.actor, args.campaign, args.import_id, args.source_sha256, args.campaign_name)
    before = inspect(engine, *values)
    print(json.dumps({'before': before, 'apply': args.apply}), flush=True)
    if not args.apply:
        return
    for lower in range(0, before['last_row'], BATCH_SIZE):
        upper = min(lower+BATCH_SIZE, before['last_row'])
        # A contention failure rolls back the current short transaction; do not
        # keep locks, mask errors, or retry arbitrary integrity/permission faults.
        for attempt in range(5):
            try:
                result = run_batch(engine, *values, lower, upper)
                break
            except Exception as error:
                sqlstate = getattr(getattr(error, 'orig', None), 'sqlstate', None)
                if sqlstate not in {'55P03', '40P01', '40001'} or attempt == 4:
                    raise
                time.sleep(.5*(attempt+1))
        print(json.dumps({'batch': result}), flush=True)
        time.sleep(.1)
    after = inspect(engine, *values)
    print(json.dumps({'after': after}), flush=True)
    if after['active_memberships'] != before['unique_contacts']:
        raise RuntimeError('Final membership coverage incomplete')


if __name__ == '__main__':
    main()

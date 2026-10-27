"""PostgreSQL is the durable import queue, progress ledger and merge authority."""
import json
import uuid
from fastapi import HTTPException
from sqlalchemy import text
from app.identity.service import query, audit, authenticate
from app.contacts.csv_input import validate_csv
from app.contacts.storage import read_source


def administrator(db, request, *, touch=True):
    user = authenticate(db, request, touch=touch)
    if user['role'] != 'admin':
        raise HTTPException(403, 'Accès administrateur requis')
    return user


def job(db, identifier, *, lock=False):
    row = query(db, 'SELECT * FROM staging.contact_imports WHERE id=:id' + (' FOR UPDATE' if lock else ''), id=identifier).mappings().first()
    if row is None:
        raise HTTPException(404, 'Import introuvable.')
    return row


def public_job(row):
    return {key: str(value) if isinstance(value, uuid.UUID) else value
            for key, value in row.items() if key not in {'source_key','source_sha256','next_publish_at'}}


def preview(db, row, mapping):
    if row['status'] not in {'mapping','preview'}:
        raise HTTPException(409, 'Cet import ne peut plus être modifié.')
    source = read_source(row['source_key'], row['source_sha256'])
    result = validate_csv(source, mapping, region=row['region'], delimiter=row['delimiter'], encoding=row['encoding'])
    query(db, 'DELETE FROM staging.contact_import_rows WHERE import_id=:id', id=row['id'])
    statement = text('''INSERT INTO staging.contact_import_rows(import_id,row_number,profile,error,warnings,duplicate_in_file)
        VALUES (:id,:number,CAST(:profile AS jsonb),:error,CAST(:warnings AS jsonb),:duplicate)''')
    for start in range(0, len(result.rows), 500):
        db.execute(statement, [dict(id=row['id'],number=r.row_number, profile=json.dumps(r.profile),
            error=r.error,warnings=json.dumps(r.warnings),duplicate=r.duplicate_in_file)
            for r in result.rows[start:start+500]])
    summary = {name:getattr(result,name) for name in ('valid_count','invalid_count','distinct_count','duplicate_count','skipped_blank')}
    query(db, '''UPDATE staging.contact_imports SET status='preview',mapping=CAST(:mapping AS jsonb),
        summary=CAST(:summary AS jsonb),total=:total,updated_at=now() WHERE id=:id''',
        id=row['id'],mapping=json.dumps(mapping),summary=json.dumps(summary),total=len(result.rows))
    return public_job(job(db,row['id']))


def apply_chunk(engine, identifier, *, limit=100):
    """A locked job and its row outcomes commit together; duplicate deliveries are safe."""
    with engine.begin() as db:
        current = query(db, '''SELECT * FROM staging.contact_imports WHERE id=:id
            AND status IN ('queued','running') FOR UPDATE SKIP LOCKED''', id=identifier).mappings().first()
        if current is None:
            return False
        rows = query(db, '''SELECT * FROM staging.contact_import_rows WHERE import_id=:id
            AND outcome IS NULL ORDER BY row_number LIMIT :limit''',id=identifier,limit=limit).mappings().all()
        counts = dict(created=0,enriched=0,unchanged=0,invalid=0)
        for row in rows:
            contact_id = None
            outcome = 'invalid'
            if not row['error']:
                profile = {k:v for k,v in row['profile'].items() if k != 'phone' and v}
                candidate = uuid.uuid4()
                inserted = query(db, '''INSERT INTO staging.contacts(id,phone,profile)
                    VALUES (:id,:phone,CAST(:profile AS jsonb)) ON CONFLICT(phone) DO NOTHING RETURNING id''',
                    id=candidate,phone=row['profile']['phone'],profile=json.dumps(profile)).scalar_one_or_none()
                contact = query(db, 'SELECT * FROM staging.contacts WHERE phone=:phone FOR UPDATE', phone=row['profile']['phone']).mappings().one()
                contact_id = contact['id']
                previous = {} if inserted else contact['profile']
                merged = {**contact['profile'],**profile}
                outcome = 'created' if inserted else ('enriched' if merged != previous else 'unchanged')
                if outcome == 'enriched':
                    query(db, 'UPDATE staging.contacts SET profile=CAST(:profile AS jsonb),updated_at=now() WHERE id=:id',id=contact_id,profile=json.dumps(merged))
                query(db, '''INSERT INTO staging.contact_history(contact_id,import_id,row_number,actor_id,action,previous_profile,incoming_profile)
                    VALUES (:contact,:job,:number,:actor,:action,CAST(:previous AS jsonb),CAST(:incoming AS jsonb))''',
                    contact=contact_id,job=identifier,number=row['row_number'],actor=current['created_by'],action=outcome,
                    previous=json.dumps(previous),incoming=json.dumps(profile))
            counts[outcome] += 1
            query(db, '''UPDATE staging.contact_import_rows SET outcome=:outcome,contact_id=:contact
                WHERE import_id=:id AND row_number=:number''', outcome=outcome,contact=contact_id,id=identifier,number=row['row_number'])
        done = current['processed'] + len(rows) == current['total']
        query(db, '''UPDATE staging.contact_imports SET processed=processed+:processed,
            created=created+:created,enriched=enriched+:enriched,unchanged=unchanged+:unchanged,invalid=invalid+:invalid,
            status=:status,updated_at=now(),next_publish_at=now(),last_error=NULL,
            completed_at=CASE WHEN :done THEN now() ELSE NULL END WHERE id=:id''',
            id=identifier,processed=len(rows),status='completed' if done else 'running',done=done,**counts)
        if done:
            audit(db,current['created_by'],'contacts.import_completed',identifier)
        return True

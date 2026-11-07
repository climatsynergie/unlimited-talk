"""Durable missed-call projection, outside media admission transactions."""
from app.identity.service import query
from app.telephony.incoming_schema import installed
from app.telephony.incoming_runtime import event
from app.telephony.inbound_service import record_missed


def process_once(engine,profile):
    if profile is None:return 0
    with engine.connect() as db:
        if not installed(db):return 0
        rows=query(db,'''SELECT * FROM staging.inbound_calls WHERE state='finished'
            AND outcome IN ('missed','abandoned','outside_hours','overflowed') AND followup_id IS NULL
            AND account_sid=:account ORDER BY finished_at,id LIMIT 20''',account=profile.account_sid).mappings().all()
    completed=0
    for row in rows:
        # Read first, then let record_missed take its canonical contact/queue
        # locks. Taking a call lock first would invert the signed-hook order.
        with engine.begin() as db:
            identifier=record_missed(db,queue_id=row['queue_id'],account_sid=row['account_sid'],call_sid=row['parent_call_sid'],
                caller_number=row['caller_number'],called_number=row['called_number'],outcome=row['outcome'],
                received_at=row['received_at'],ended_at=row['finished_at'])
            changed=query(db,'''UPDATE staging.inbound_calls SET followup_id=:followup WHERE id=:id AND followup_id IS NULL
                RETURNING id''',id=row['id'],followup=identifier).first()
            if changed:
                event(db,row['id'],'followup.created',{'followup_id':str(identifier)})
                completed+=1
    return completed

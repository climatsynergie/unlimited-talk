"""Reconcile committed PG outbox jobs, including lost broker messages."""
import logging
import time
from pathlib import Path
from app.database import make_engine
from app.identity.service import query
from app.contacts.tasks import apply

logger=logging.getLogger(__name__)


def dispatch_once(engine, publish):
    with engine.begin() as db:
        rows=query(db,"""SELECT id FROM staging.contact_imports WHERE status IN ('queued','running')
            AND next_publish_at<=now() ORDER BY next_publish_at LIMIT 10 FOR UPDATE SKIP LOCKED""").mappings().all()
        for row in rows:
            publish(str(row['id']))
            query(db,"UPDATE staging.contact_imports SET next_publish_at=now()+interval '30 seconds' WHERE id=:id",id=row['id'])
        return len(rows)


def main():
    engine=make_engine()
    while True:
        try:
            dispatch_once(engine,lambda identifier: apply.apply_async(args=[identifier],retry=False))
            Path('/tmp/dispatcher-heartbeat').touch()
        except Exception:
            # Never log broker URLs or payloads. Uncommitted publication retries are safe.
            logger.warning('Import dispatcher retry pending')
        time.sleep(5)


if __name__=='__main__':
    main()

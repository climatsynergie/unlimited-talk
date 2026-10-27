"""JSON-only Celery transport. No contact data or result backend in Redis."""
import os
import time
from pathlib import Path
from celery import Celery
from kombu import Queue

password = Path(os.environ['BROKER_PASSWORD_FILE']).read_text().strip()
# Password is generated as hexadecimal by provisioning, never a user URL.
if len(password)<32 or any(c not in '0123456789abcdef' for c in password):
    raise RuntimeError('Invalid broker credential')
celery = Celery('contacts',broker='redis://:'+password+'@broker:6379/0')
celery.conf.update(task_serializer='json',accept_content=['json'],task_ignore_result=True,
    task_acks_late=True,task_reject_on_worker_lost=True,worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,broker_transport_options={'visibility_timeout':120,'socket_connect_timeout':3,'socket_timeout':3},
    task_queues=[Queue('imports')],task_default_queue='imports',worker_enable_remote_control=False,
    task_time_limit=90,task_soft_time_limit=80)
_engine=None


@celery.task(name='contacts.apply',ignore_result=True)
def apply(identifier):
    global _engine
    from app.database import make_engine
    from app.contacts.service import apply_chunk
    if _engine is None:
        _engine=make_engine()
    # Database rollback plus dispatcher reconciliation recovers all failures.
    deadline=time.monotonic()+60
    while time.monotonic()<deadline and apply_chunk(_engine,identifier):
        pass

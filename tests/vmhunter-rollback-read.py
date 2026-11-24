"""Run using the preceding release's app package and disposable PG only."""
import json
import os
from pathlib import Path
from uuid import UUID

from app.database import make_engine
from app.identity.service import query
from app.telephony import service
from app.main import COMPATIBLE_SCHEMA_REVISIONS

assert os.environ['DB_HOST']=='db' and os.environ['COMMUNICATIONS_MODE']=='disabled'
assert Path(service.__file__).is_relative_to('/previous/app')
assert '0012_incoming_runtime' in COMPATIBLE_SCHEMA_REVISIONS
engine=make_engine()
with engine.connect() as db:
    query(db,'SET TRANSACTION READ ONLY')
    assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
    assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'
    identifiers=query(db,'SELECT id FROM staging.voice_intents WHERE campaign_id=:campaign ORDER BY id',
        campaign=UUID('2bdf5195-0b52-49b1-aecc-0caaf5459e77')).scalars().all()
    assert len(identifiers)==3
    for identifier in identifiers:
        history=service.history(db,identifier)
        assert history['intent']['state']=='finished'
        assert len([e for e in history['events'] if e['kind']=='vmhunter.claim'])==1
        assert len([e for e in history['events'] if e['kind']=='vmhunter.result'])==1
    assert query(db,'SHOW transaction_read_only').scalar_one()=='on'
print(json.dumps({'preceding_revision':os.environ['PREVIOUS_REVISION'],
    'preceding_code_reads_new_event_kinds':True,'intents_verified':3,
    'schema':'0012_incoming_runtime','destructive_downgrade_required':False,'read_only':True}))
engine.dispose()

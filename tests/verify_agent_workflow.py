"""Run the actual browser/API/PG call workflow with a synthetic provider only."""
import hashlib,json,os,secrets,shlex,subprocess,tempfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
extra=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
if not any(x in {'-f','--file'} or x.startswith('--file=') for x in extra):extra+=['-f',str(root/'compose.yaml')]
compose=['sudo','-n','docker','compose','--project-directory',str(root),*extra]
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE']=='disabled'
with tempfile.TemporaryDirectory(prefix='ut-agent-qa-') as folder:
    override=Path(folder)/'workflow.yaml'
    token=secrets.token_hex(32)
    override.write_text(json.dumps({'services':{'api':{
        'command':['python','/qa/agent_workflow_server.py'],
        'environment':{'QA_FIXTURE_TOKEN':token,'PYTHONPATH':'/app'},
        'volumes':[str(root/'tests/agent_workflow_server.py')+':/qa/agent_workflow_server.py:ro'],
    }}}))
    override.chmod(0o600)
    env={**os.environ,'FOUNDATION_COMPOSE_ARGS':shlex.join([*extra,'-f',str(override)]),
         'QA_REAL_WORKFLOW':'1','QA_FIXTURE_TOKEN':token}
    try:
        subprocess.run(['python3',str(root/'tests/verify_browser.py'),'agent-workflow.spec.ts'],cwd=root,env=env,check=True,timeout=240)
        # A skipped test must never turn this release gate green. Confirm its
        # persisted evidence independently after the browser process exits.
        prefix='Parcours agent QA '+hashlib.sha256(token.encode()).hexdigest()[:16]+' %'
        proof='''from app.database import make_engine
from sqlalchemy import text
with make_engine().begin() as db:
 db.execute(text('SET TRANSACTION READ ONLY'))
 count=db.execute(text("""SELECT count(*) FROM staging.campaigns ca WHERE ca.name LIKE :prefix
   AND (SELECT count(*) FROM staging.voice_intents i WHERE i.campaign_id=ca.id AND i.state='finished')=2
   AND (SELECT count(*) FROM staging.campaign_contacts m JOIN staging.contacts c ON c.id=m.contact_id
     WHERE m.campaign_id=ca.id AND c.non_interested)=1"""),{'prefix':PREFIX}).scalar_one()
 assert count==2,'Real workflow evidence is missing; a skipped browser test cannot pass.'
print('Real browser/API/PostgreSQL workflow evidence: PASS')
'''.replace('PREFIX',repr(prefix))
        subprocess.run([*compose,'exec','-T','api','python','-'],input=proof,text=True,check=True,timeout=30)
    finally:
        subprocess.run([*compose,'up','-d','--no-deps','--no-build','--wait','--wait-timeout','120','api'],check=True)

"""Create a private, read-only logical snapshot on the authorized deployment host.

Run over the existing root SSH identity. No provider call or application restart.
The default validates schema-only backup; --data makes the pre-migration snapshot.
The remote credentials remain on their existing host and are never printed.
"""
import argparse,datetime,hashlib,json,subprocess
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--data',action='store_true');args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
folder=root/'qa-reports/evidence/release-preparation';folder.mkdir(exist_ok=True)
program=r'''import datetime,hashlib,json,os,pathlib,subprocess,time
os.umask(0o077)
image='postgres:18-alpine@sha256:123b17998ccaf47e53b502e8c6a1e79afd8f579c6f3eec83c563da026f957395'
current=pathlib.Path('/srv/unlimited-talk-staging/current').resolve(strict=True)
compose=['docker','compose','--project-directory',str(current),'--env-file',str(current/'.env'),'-f',str(current/'compose.managed.yaml')]
config=json.loads(subprocess.check_output([*compose,'config','--format','json'],text=True))
assert config['name']=='unlimited-talk-staging-managed'
env=config['services']['migrate']['environment'];assert env['DB_SSLMODE']=='verify-full'
assert env['DB_NAME']=='unlimited_talk_staging' and env['DB_USER']=='ut_staging_migrator'
secrets=config['secrets'];password_path=pathlib.Path(secrets['migrator_password']['file']);ca=pathlib.Path(secrets['postgres_ca']['file'])
password=password_path.read_text().strip();assert password and ca.is_file()
network=config['networks']['staging']['name']
result=subprocess.run(['docker','pull',image],capture_output=True,text=True,timeout=180)
assert result.returncode==0,'Unable to retrieve the pinned PostgreSQL client'
backup=pathlib.Path('/var/backups/unlimited-talk-staging');backup.mkdir(mode=0o700,parents=True,exist_ok=True);assert backup.stat().st_uid==0 and backup.stat().st_mode&0o077==0
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
kind='data' if INCLUDE_DATA else 'schema'
filename=f'pre-405dc5a-{kind}-{stamp}.dump';output=backup/filename
with os.fdopen(os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb'):pass
passfile=backup/('.pgpass-'+stamp)
def escaped(value):return str(value).replace(chr(92),chr(92)*2).replace(':',chr(92)+':')
with os.fdopen(os.open(passfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as stream:
 stream.write(':'.join(escaped(v) for v in [env['DB_HOST'],env.get('DB_PORT','25060'),env['DB_NAME'],env['DB_USER'],password])+'\n')
started=time.monotonic()
try:
 command=['docker','run','--rm','--network',network,'--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=16m','--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','256m','--cpus','0.25','--pids-limit','64']
 values={'PGHOST':env['DB_HOST'],'PGPORT':str(env.get('DB_PORT','25060')),'PGDATABASE':env['DB_NAME'],'PGUSER':env['DB_USER'],'PGSSLMODE':'verify-full','PGSSLROOTCERT':'/run/postgres-ca','PGPASSFILE':'/run/pgpass','PGCONNECT_TIMEOUT':'15','PGOPTIONS':'-c default_transaction_read_only=on'}
 for key,value in values.items():command+=['-e',key+'='+value]
 command+=['-v',str(passfile)+':/run/pgpass:ro','-v',str(ca)+':/run/postgres-ca:ro','-v',str(backup)+':/backup','--entrypoint','pg_dump',image,'--format=custom','--schema=staging','--no-owner','--no-privileges','--file=/backup/'+filename]
 if not INCLUDE_DATA:command+=['--schema-only']
 result=subprocess.run(command,capture_output=True,text=True,timeout=300)
 if result.returncode:
  print(json.dumps({'status':'FAIL','phase':'pg_dump','exit_code':result.returncode,'error_output_retained_on_host':True,'duration_seconds':round(time.monotonic()-started,3)}))
  (backup/(filename+'.error')).write_text(result.stderr)
  raise SystemExit(result.returncode)
 assert output.stat().st_size>5 and output.open('rb').read(5)==b'PGDMP'
 verify=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','128m','--pids-limit','32','-v',str(output)+':/snapshot.dump:ro','--entrypoint','pg_restore',image,'--list','/snapshot.dump']
 checked=subprocess.run(verify,capture_output=True,text=True,timeout=60)
 assert checked.returncode==0,'Snapshot table-of-contents verification failed'
 table_data_entries=sum(' TABLE DATA ' in line for line in checked.stdout.splitlines())
 if INCLUDE_DATA:assert table_data_entries>0,'Full snapshot has no table-data sections'
 payload=subprocess.run(verify[:-2]+['--file=/dev/null','--no-owner','--no-privileges','/snapshot.dump'],capture_output=True,text=True,timeout=120)
 assert payload.returncode==0,'Snapshot payload could not be fully decoded offline'
 (backup/(filename+'.toc')).write_text(checked.stdout)
 info={'status':'PASS','kind':kind,'path':str(output),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'pg_dump_exit':result.returncode,'pg_restore_list_exit':checked.returncode,'archive_payload_read_exit':payload.returncode,'table_data_entries':table_data_entries,'duration_seconds':round(time.monotonic()-started,3),'data_only_on_original_host':True,'database_writes':False,'full_restore_executed':False,'current_release':current.name}
 (backup/(filename+'.json')).write_text(json.dumps(info,indent=2)+'\n');print(json.dumps(info))
finally:
 passfile.unlink(missing_ok=True)
'''.replace('INCLUDE_DATA',repr(args.data))
# The remote source is retained for exact reproduction; it contains no passwords.
label='snapshot-data' if args.data else 'snapshot-schema'
script=folder/(label+'-remote-'+hashlib.sha256(program.encode()).hexdigest()[:12]+'.py')
if script.exists():assert script.read_text()==program
else:script.write_text(program);script.chmod(0o600)
command=['ssh','-i','/home/codexdev/.ssh/unlimited-talk-staging','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','root@143.198.41.24','python3','-']
started=datetime.datetime.now(datetime.timezone.utc).isoformat()
result=subprocess.run(command,input=program,text=True,capture_output=True,timeout=620)
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
(folder/(label+'-'+stamp+'.log')).write_text(result.stdout+result.stderr)
record={'command':command,'stdin_source':script.name,'script_sha256':hashlib.sha256(program.encode()).hexdigest(),'started_at':started,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'exit_code':result.returncode}
(folder/(label+'-'+stamp+'.json')).write_text(json.dumps(record,indent=2)+'\n')
print(result.stdout);print('ssh_exit',result.returncode)
if result.returncode:print('Remote details are retained privately; no secret output copied.')
raise SystemExit(result.returncode)

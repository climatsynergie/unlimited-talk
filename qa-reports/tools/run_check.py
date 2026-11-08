"""Evidence recorder: preserves stdout/stderr, actual exit code and source context."""
import argparse,datetime,hashlib,json,os,signal,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('check');p.add_argument('--timeout',type=int,default=900);p.add_argument('--cwd');p.add_argument('command',nargs=argparse.REMAINDER)
a=p.parse_args();command=a.command[1:] if a.command[:1]==['--'] else a.command
if not command:p.error('command required')
root=Path(__file__).resolve().parents[2];folder=root/'qa-reports/evidence';folder.mkdir(parents=True,exist_ok=True)
name=''.join(c if c.isalnum() or c in '-_.' else '_' for c in a.check)
if (folder/(name+'.log')).exists() or (folder/(name+'.json')).exists():
 name += '-retry-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%f')
log=folder/(name+'.log');meta=folder/(name+'.json')
started=datetime.datetime.now(datetime.timezone.utc).isoformat();clock=time.monotonic()
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
try:
 with log.open('wb') as output:
  process=subprocess.Popen(command,cwd=a.cwd or root,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
  try:code=process.wait(timeout=a.timeout);status='PASS' if code==0 else 'FAIL'
  except subprocess.TimeoutExpired:
   os.killpg(process.pid,signal.SIGTERM)
   try:process.wait(timeout=15)
   except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
   code=124;status='BLOCKED'
except OSError as error:
 log.write_text(type(error).__name__+': '+str(error)+'\n');code=127;status='BLOCKED'
patch_hash=hashlib.sha256(subprocess.check_output(['git','diff','--binary'],cwd=root)).hexdigest()
record=dict(working_diff_sha256=patch_hash,check=name,command=command,cwd=str(a.cwd or root),revision=revision,started_at=started,
 finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),duration_seconds=round(time.monotonic()-clock,3),
 exit_code=code,status=status,log=str(log.relative_to(root)),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
meta.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record));raise SystemExit(code)

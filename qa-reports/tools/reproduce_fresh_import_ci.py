"""Reproduce the canonical CI prefix on fresh local-only Docker state.

Only runs in the dedicated GitHub diagnostic branch. Provider traffic is
explicitly disabled; no production credentials, SSH, deployment or data access.
"""
from pathlib import Path
import json,os,re,subprocess,sys
root=Path(__file__).resolve().parents[2]
assert os.environ.get('GITHUB_REPOSITORY')=='climatsynergie/unlimited-talk'
assert os.environ.get('GITHUB_REF')=='refs/heads/ops/shift-ci-diagnostics-20261127'
config=json.loads(subprocess.check_output(['docker','compose','config','--format','json'],cwd=root))
assert config['services']['api']['environment']['DB_HOST']=='db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE']=='disabled'

def checked(args,label,timeout=240):
 print('Running isolated diagnostic stage:',label,flush=True)
 result=subprocess.run(args,cwd=root,capture_output=True,text=True,timeout=timeout)
 if result.returncode:
  selected=[]
  for line in (result.stdout+'\n'+result.stderr).splitlines():
   if not re.search(r'(?:FAIL|ERROR): test_|test_.*\.\.\. (?:FAIL|ERROR)|[A-Za-z_]+Error:|psycopg\.errors\.|sqlalchemy\.exc\.|^Ran \d+ tests|^FAILED|^  File ',line):continue
   if re.search(r'password|secret|token|authorization|bearer|credential',line,re.I):line=line.split(':',1)[0]+': [sensitive content redacted]'
   line=re.sub(r'(?:AC|SK|CA|RE)[0-9a-fA-F]{32}|\+\d{9,15}','[synthetic identifier]',line)
   selected.append(line[:800])
  record=json.dumps(dict(stage=label,exit_code=result.returncode,lines=selected),indent=2)
  print('::notice title=Fresh synthetic import failure::'+record.replace('%','%25').replace(chr(13),'%0D').replace(chr(10),'%0A'),flush=True)
  raise SystemExit(result.returncode)
 print('Stage passed:',label,flush=True)

for name in ('contacts','campaign','calendar','callbacks','voice','recordings','inbound','dialer','long_recordings','incoming'):
 checked(['python3','tests/verify_'+name+'_upgrade.py'],'migration-'+name)
checked(['docker','compose','up','-d','--no-build','--wait','--wait-timeout','180'],'all-isolated-services')
for name in ('dialer_queue_index','foundation','identity','imports'):
 checked(['python3','tests/verify_'+name+'.py'],'prefix-'+name)
for number in range(1,11):
 checked(['python3','tests/verify_import_dispatch_race.py'],'import-race-'+str(number))
print('Fresh canonical CI prefix and ten six-test import regressions passed.',flush=True)

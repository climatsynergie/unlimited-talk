"""Standalone container driver; records explicit limits, exits and OOM evidence."""
from pathlib import Path
import subprocess,json,datetime,time
root=Path(__file__).resolve().parents[2];folder=root/'qa-reports/evidence/backend'
image='unlimited-talk-qa-audit:dispatch-fixed'
image_info=json.loads(subprocess.check_output(['sudo','-n','docker','image','inspect',image]))[0]
for concurrency,label in ((1,'single'),(2,'double')):
 for suffix in ('.log','.json'):
  old=folder/('csv-capacity-'+label+suffix)
  if old.exists():
   stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
   old.rename(folder/('csv-capacity-'+label+'-previous-'+stamp+suffix))
 name='ut-qa-csv-capacity-'+label
 command=['sudo','-n','docker','run','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','100','--memory','512m','--memory-swap','512m','--cpus','0.5','--tmpfs','/tmp:rw,noexec,nosuid,size=32m','-e','COVERAGE_PROCESS_START=','-e','PYTHONPATH=/app','-v','/tmp/ut-qa-csv-capacity/near-cap.csv:/fixtures/near-cap.csv:ro','-v',str(root/'qa-reports/tools/csv_parser_capacity.py')+':/qa/csv_parser_capacity.py:ro','--entrypoint','python',image,'/qa/csv_parser_capacity.py','--concurrency',str(concurrency)]
 started=datetime.datetime.now(datetime.timezone.utc).isoformat();clock=time.monotonic()
 result=subprocess.run(command,capture_output=True,text=True,timeout=240)
 state=json.loads(subprocess.check_output(['sudo','-n','docker','inspect',name]))[0]
 metadata=dict(concurrency=concurrency,command=command,image_id=image_info['Id'],started_at=started,ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),elapsed_host_seconds=time.monotonic()-clock,exit_code=result.returncode,container_state=state['State'],memory_limit=state['HostConfig']['Memory'],memory_swap_limit=state['HostConfig']['MemorySwap'],cpu_quota_nanos=state['HostConfig']['NanoCpus'],network_mode=state['HostConfig']['NetworkMode'])
 (folder/('csv-capacity-'+label+'.log')).write_text('$ '+' '.join(command)+'\n'+result.stdout+result.stderr+'\nEXIT_CODE='+str(result.returncode)+'\n')
 (folder/('csv-capacity-'+label+'.json')).write_text(json.dumps(metadata,indent=2))
 print(json.dumps(metadata),flush=True);print(result.stdout+result.stderr,flush=True)
 subprocess.run(['sudo','-n','docker','rm',name],check=True,stdout=subprocess.DEVNULL)

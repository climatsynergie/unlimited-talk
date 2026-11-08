"""Remember image identity across ephemeral API replacements for exact-source coverage."""
import json,subprocess,time,os
from pathlib import Path
root=Path(__file__).resolve().parents[2];folder=root/'qa-reports/coverage';target=folder/os.environ.get('QA_COVERAGE_RECORD','final-containers.json');stop=folder/os.environ.get('QA_COVERAGE_STOP','stop-collector')
image=subprocess.check_output(['sudo','-n','docker','image','inspect',os.environ.get('QA_COVERAGE_IMAGE','unlimited-talk-qa-audit:fixed'),'--format','{{.Id}}'],text=True).strip();seen={}
while not stop.exists():
 ids=subprocess.check_output(['sudo','-n','docker','ps','-aq','--filter','ancestor='+image],text=True).split()
 if ids:
  result=subprocess.run(['sudo','-n','docker','inspect',*ids],text=True,capture_output=True)
  if result.returncode==0:
   for row in json.loads(result.stdout):
    # Only QA containers instrumented by this audit are eligible.
    mounts=row.get('Mounts',[])
    if any(m['Destination']=='/qa-coverage' and m['Source']==str(folder/'final-data') for m in mounts):
     seen[row['Config']['Hostname']]=dict(id=row['Id'],image=row['Image'],name=row['Name'])
 target.write_text(json.dumps(dict(image=image,containers=seen),indent=2)+'\n')
 time.sleep(1)

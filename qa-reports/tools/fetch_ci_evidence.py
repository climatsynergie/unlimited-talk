"""Read public GitHub validation evidence; never publishes, merges or deploys."""
import hashlib,json,urllib.request,urllib.error,zipfile,io
from pathlib import Path
root=Path(__file__).resolve().parents[2];folder=root/'qa-reports/evidence';run=42537634865
base=f'https://api.github.com/repos/climatsynergie/unlimited-talk/actions/runs/{run}'
def get(url):
 return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'UnlimitedTalks-QA-audit','Accept':'application/vnd.github+json'}),timeout=30)
with get(base) as response:metadata=json.load(response)
with get(base+'/jobs') as response:jobs=json.load(response)
assert metadata['head_sha']=='e09d9e496440d333a6433c595b2bf6d46cc66e85'
assert metadata['status']=='completed' and metadata['conclusion']=='success'
assert next(j for j in jobs['jobs'] if j['name']=='test')['conclusion']=='success'
assert next(j for j in jobs['jobs'] if j['name']=='publish')['conclusion']=='skipped'
(folder/'github-ci-run-final.json').write_text(json.dumps(metadata,indent=2)+'\n');(folder/'github-ci-jobs-final.json').write_text(json.dumps(jobs,indent=2)+'\n')
result=dict(run_id=run,url=metadata['html_url'],commit=metadata['head_sha'],status='PASS',conclusion=metadata['conclusion'],test='success',publish='skipped',exit_code=None,exit_code_note='GitHub API exposes step/job conclusions, not process exit codes. Local checks retain actual exit codes.',log_download=None)
try:
 with get(base+'/logs') as response:data=response.read(32*1024*1024+1)
 assert len(data)<=32*1024*1024,'CI archive exceeds audit bound'
 with zipfile.ZipFile(io.BytesIO(data)) as archive:
  assert sum(x.file_size for x in archive.infolist())<=128*1024*1024
  target=folder/'github-ci-logs';target.mkdir(exist_ok=True)
  for item in archive.infolist():
   if item.is_dir():continue
   name=''.join(c if c.isalnum() or c in '-_.' else '_' for c in item.filename)
   (target/name).write_bytes(archive.read(item))
 (folder/'github-ci-logs.zip').write_bytes(data)
 result['log_download']=dict(status='PASS',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
except urllib.error.HTTPError as error:
 result['log_download']=dict(status='BLOCKED',http_status=error.code,reason='Public API log download requires additional authorization; no credential bypass attempted.')
(folder/'github-ci-validation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

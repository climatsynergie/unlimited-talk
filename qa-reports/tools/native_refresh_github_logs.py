"""One bounded unauthenticated logs request; no auth lookup or alternate route."""
import argparse,datetime,hashlib,io,json,urllib.error,urllib.request,zipfile,re
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);args=parser.parse_args()
root=Path(__file__).resolve().parents[2];folder=root/'qa-reports/evidence/native-refresh/github';folder.mkdir(exist_ok=True)
url='https://api.github.com/repos/climatsynergie/unlimited-talk/actions/runs/'+args.run_id+'/logs'
request=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'UnlimitedTalk-QA-ReadOnly','X-GitHub-Api-Version':'2022-11-28'})
result=dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),run_id=args.run_id,url=url,authentication='none/public GET',maximum_bytes=16*1024*1024)
try:
 with urllib.request.urlopen(request,timeout=30) as response:
  raw=response.read(result['maximum_bytes']+1)
  result.update(status=response.status,content_type=response.headers.get('Content-Type'),bytes=len(raw),truncated=len(raw)>result['maximum_bytes'],sha256=hashlib.sha256(raw).hexdigest())
  if not result['truncated']:
   (folder/('run-'+args.run_id+'-public-logs.zip')).write_bytes(raw)
   with zipfile.ZipFile(io.BytesIO(raw)) as archive:
    summaries=[]
    for info in archive.infolist():
     if info.file_size>32*1024*1024:
      summaries.append(dict(member=info.filename,skipped='uncompressed member exceeds32MiB'));continue
     text=archive.read(info).decode('utf-8','replace');text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
     matches=[line[:1200] for line in text.splitlines() if re.search(r'\bRan \d+ tests? in |\b\d+ passed(?:\s|\()|\b\d+ failed(?:\s|\()|\b\d+ skipped(?:\s|\()|Process completed with exit code \d+',line)]
     if matches:summaries.append(dict(member=info.filename,raw_summary_lines=matches))
    result['raw_count_summary_matches']=summaries
except urllib.error.HTTPError as error:
 result.update(status=error.code,body=error.read(8192).decode('utf-8','replace'),raw_counts_available=False,numeric_process_exits='unknown')
except Exception as error:result.update(error=type(error).__name__+': '+str(error),raw_counts_available=False,numeric_process_exits='unknown')
(folder/('run-'+args.run_id+'-public-log-attempt.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

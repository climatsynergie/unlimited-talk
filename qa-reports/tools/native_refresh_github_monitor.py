"""Read-only public GitHub workflow/job metadata, no dispatch or deployment."""
import argparse,datetime,json,urllib.request,urllib.error
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--sha',default='405dc5a611da7795ecac85b7302c54702502e9b8');args=parser.parse_args()
root=Path(__file__).resolve().parents[2];folder=root/'qa-reports/evidence/native-refresh/github';folder.mkdir(exist_ok=True)
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');observed=datetime.datetime.now(datetime.timezone.utc).isoformat()
url='https://api.github.com/repos/climatsynergie/unlimited-talk/actions/runs?head_sha='+args.sha+'&per_page=20'
def get(url):
 request=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'UnlimitedTalk-QA-ReadOnly','X-GitHub-Api-Version':'2022-11-28'})
 try:
  with urllib.request.urlopen(request,timeout=30) as response:
   return dict(url=url,status=response.status,rate_remaining=response.headers.get('X-RateLimit-Remaining'),rate_reset=response.headers.get('X-RateLimit-Reset'),data=json.load(response))
 except urllib.error.HTTPError as error:return dict(url=url,status=error.code,body=error.read().decode()[:2000],rate_remaining=error.headers.get('X-RateLimit-Remaining'))
response=get(url);runs=response.get('data',{}).get('workflow_runs',[]);summary=[]
for run in runs:
 item={key:run.get(key) for key in ('id','name','head_sha','head_branch','event','status','conclusion','html_url','run_number','run_attempt','created_at','updated_at')}
 jobs=get(run['jobs_url']+'?per_page=100');item['jobs_response_status']=jobs['status'];item['jobs']=[{key:job.get(key) for key in ('id','name','status','conclusion','started_at','completed_at','html_url','steps')} for job in jobs.get('data',{}).get('jobs',[])]
 summary.append(item)
 result_path=folder/(stamp+'-run-'+str(run['id'])+'-jobs.json');result_path.write_text(json.dumps(jobs,indent=2))
result=dict(observed_at=observed,requested_sha=args.sha,authentication='none/public GET',response_status=response['status'],rate_remaining=response.get('rate_remaining'),total_count=response.get('data',{}).get('total_count'),runs=summary)
(folder/(stamp+'-runs-response.json')).write_text(json.dumps(response,indent=2));(folder/(stamp+'-summary.json')).write_text(json.dumps(result,indent=2));(folder/'latest-summary.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))

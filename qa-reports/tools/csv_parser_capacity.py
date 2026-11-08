"""Parser memory experiment; no lifespan, DB/API clients, secrets or network."""
import argparse,json,os,resource,time,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
args=argparse.ArgumentParser();args.add_argument('--concurrency',type=int,choices=(1,2),required=True);options=args.parse_args()
def rss():
 return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
def cgroup():
 result={}
 for name in ('memory.current','memory.peak','memory.events'):
  path=Path('/sys/fs/cgroup')/name
  try:result[name]=path.read_text().strip()
  except OSError:result[name]=None
 return result
start=time.monotonic();before_import=rss()
import app.main  # Loads actual API modules; do not enter application lifespan.
from app.contacts.csv_input import validate_csv
mapping=dict(zip(('phone','first_name','last_name','display_name','email','address','city','province','postal_code'),('telephone','prenom','nom','nomcomplet','courriel','adresse','ville','province','codepostal')))
print(json.dumps(dict(event='baseline',concurrency=options.concurrency,rss_bytes=rss(),before_import_bytes=before_import,maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,app_import_seconds=time.monotonic()-start,cgroup=cgroup())),flush=True)
barrier=threading.Barrier(options.concurrency)
def parse(index):
 source=Path('/fixtures/near-cap.csv').read_bytes()  # Separate request bytes per parser, counted in budget.
 barrier.wait(timeout=30)
 started=time.monotonic()
 result=validate_csv(source,mapping,delimiter=',')
 elapsed=time.monotonic()-started
 assert len(result.rows)==100000 and result.valid_count==100000 and result.invalid_count==0
 assert result.distinct_count==100000 and result.duplicate_count==0
 print(json.dumps(dict(event='parser_complete',index=index,elapsed_seconds=elapsed,source_bytes=len(source),parsed_rows=len(result.rows),valid_count=result.valid_count,distinct_count=result.distinct_count,rss_bytes=rss(),maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,cgroup=cgroup())),flush=True)
 return result
started=time.monotonic()
with ThreadPoolExecutor(max_workers=options.concurrency) as pool:results=list(pool.map(parse,range(options.concurrency)))
print(json.dumps(dict(event='result',status='PASS',concurrency=options.concurrency,rows_each=[len(row.rows) for row in results],elapsed_seconds=time.monotonic()-started,process_seconds=time.monotonic()-start,rss_bytes=rss(),maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,cgroup=cgroup())),flush=True)

"""Compare streamed candidate APK origins with fresh primary secdb snapshots."""
import datetime,json,shlex,subprocess,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'qa-reports/evidence/native-refresh'
records=json.loads((OUT/'inventories.json').read_text());cache={};reports=[]
comparator='unlimited-talk-qa-audit:dependency-hardened'
for record in records:
 if 'error' in record:
  reports.append(record);continue
 branch='v'+'.'.join(record['alpine_release'].split('.')[:2]);advisories={};sources=[]
 for repository in ('main','community'):
  url=f'https://secdb.alpinelinux.org/{branch}/{repository}.json';sources.append(url)
  if url not in cache:
   raw=urllib.request.urlopen(url,timeout=30).read();cache[url]=json.loads(raw)
   (OUT/f'alpine-{branch}-{repository}.json').write_bytes(raw)
  for item in cache[url]['packages']:
   package=item['pkg'];advisories[package['name']]=package.get('secfixes',{})
 checks=[]
 for package in record['packages']:
  for version,cves in advisories.get(package['origin'],{}).items():
   if version!='0':checks.append((package,version,cves))
 script='\n'.join('apk version -t '+shlex.quote(package['version'])+' '+shlex.quote(version) for package,version,_ in checks)+'\n'
 command=['sudo','-n','docker','run','--rm','--pull','never','-i','--network','none','--read-only','--memory','64m','--pids-limit','32','--cap-drop','ALL','--security-opt','no-new-privileges:true','--entrypoint','sh',comparator]
 result=subprocess.run(command,input=script,capture_output=True,text=True,timeout=60)
 order=result.stdout.splitlines();assert result.returncode==0,(record['name'],result.returncode,result.stderr);assert len(order)==len(checks),(record['name'],len(order),len(checks),result.stderr)
 hits=[dict(package=p['name'],origin=p['origin'],installed=p['version'],fixed=fix,advisories=cves) for (p,fix,cves),comparison in zip(checks,order) if comparison=='<']
 output=dict(name=record['name'],repository=record['repository'],tag=record['tag'],index_digest=record['index_digest'],platform_digest=record['platform_digest'],alpine=record['alpine_release'],package_count=record['package_count'],comparisons=len(checks),scope='APK-origin version ranges only; excludes bundled CPython/Node/wheels and reachability. A hit is not an exploit proof.',sources=sources,known_unfixed=hits,apk_comparator=dict(command=command,exit_code=result.returncode),at=datetime.datetime.now(datetime.timezone.utc).isoformat())
 reports.append(output);(OUT/record['name']/'apk-advisories.json').write_text(json.dumps(output,indent=2))
 print(json.dumps(dict(name=record['name'],alpine=record['alpine_release'],package_count=record['package_count'],hits=hits)),flush=True)
(OUT/'apk-advisories.json').write_text(json.dumps(reports,indent=2))

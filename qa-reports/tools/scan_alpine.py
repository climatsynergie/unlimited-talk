"""Compare installed APK origins with Alpine's current main/community secdb."""
import json,subprocess,urllib.request,datetime
from pathlib import Path
root=Path(__file__).resolve().parents[2];folder=root/'qa-reports/evidence'
images={'api':'unlimited-talk-qa-audit:fixed','gateway':'nginxinc/nginx-unprivileged:stable-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03','db':'postgres:18-alpine@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873','broker':'redis:8.2-alpine@sha256:35bf3d49a07b693d8defb4e4fc9ef8c663f71c2993f181eba99c7b72966c1f9b'}
reports={};cache={}
for component,image in images.items():
 raw=subprocess.check_output(['sudo','-n','docker','run','--rm','--network','none','--entrypoint','sh',image,'-c','cat /etc/alpine-release; cat /lib/apk/db/installed'],text=True)
 (folder/f'os-installed-{component}.txt').write_text(raw)
 release,raw=raw.split('\n',1);branch='v'+'.'.join(release.split('.')[:2]);packages=[]
 for section in raw.split('\n\n'):
  fields=dict(line.split(':',1) for line in section.splitlines() if ':' in line)
  if 'P' in fields:packages.append(fields)
 advisories={};sources=[]
 for repo in ('main','community'):
  url=f'https://secdb.alpinelinux.org/{branch}/{repo}.json';sources.append(url)
  if url not in cache:
   data=urllib.request.urlopen(url,timeout=30).read();cache[url]=json.loads(data);(folder/f'alpine-{branch}-{repo}.json').write_bytes(data)
  for item in cache[url]['packages']:
   pkg=item['pkg'];advisories[pkg['name']]=pkg.get('secfixes',{})
 comparisons=[]
 for pkg in packages:
  for fix,cves in advisories.get(pkg.get('o',pkg['P']),{}).items():
   if fix=='0':continue
   comparisons.append((pkg,fix,cves))
 # APK's own comparator handles revision/epoch ordering, unlike semver.
 script='\n'.join('apk version -t '+__import__('shlex').quote(p['V'])+' '+__import__('shlex').quote(fix) for p,fix,cves in comparisons)
 result=subprocess.check_output(['sudo','-n','docker','run','--rm','-i','--network','none','--entrypoint','sh',image],input=script,text=True).splitlines() if comparisons else []
 assert len(result)==len(comparisons)
 hits=[dict(package=p['P'],origin=p.get('o',p['P']),installed=p['V'],fixed=fix,advisories=cves) for (p,fix,cves),ordering in zip(comparisons,result) if ordering=='<']
 reports[component]=dict(image=image,release=release,packages=len(packages),sources=sources,known_unfixed=hits)
 print(component,release,len(packages),'packages;',len(hits),'unfixed advisory ranges')
report=dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),scope='APK package origins only; excludes CPython compiled in /usr/local and build-only Node dependencies',components=reports)
(folder/'alpine-advisory-results.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(any(r['known_unfixed'] for r in reports.values()))

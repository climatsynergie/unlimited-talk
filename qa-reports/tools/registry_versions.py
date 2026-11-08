import json,urllib.request
from pathlib import Path
repos={'python':('library/python','3.12-alpine'),'nginx':('nginxinc/nginx-unprivileged','stable-alpine'),'postgres':('library/postgres','18-alpine'),'redis':('library/redis','8.2-alpine')}
root=Path(__file__).resolve().parents[2];report={}
for name,(repo,tag) in repos.items():
 token=json.load(urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io&scope=repository:'+repo+':pull',timeout=30))['token']
 def get(ref):
  request=urllib.request.Request('https://registry-1.docker.io/v2/'+repo+'/manifests/'+ref,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'})
  with urllib.request.urlopen(request,timeout=30) as r:return json.load(r),r.headers.get('Docker-Content-Digest')
 index,digest=get(tag);platform=next(m for m in index['manifests'] if m['platform']['architecture']=='amd64' and m['platform']['os']=='linux');manifest,_=get(platform['digest'])
 report[name]=dict(repository=repo,tag=tag,digest=digest,amd64=platform['digest'],compressed_bytes=sum(x['size'] for x in manifest['layers']))
 print(name,report[name])
(root/'qa-reports/evidence/current-image-version-results.json').write_text(json.dumps(report,indent=2))

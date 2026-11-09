"""Read-only official registry metadata and streaming package inventory; no pulls."""
import concurrent.futures,datetime,hashlib,json,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'qa-reports/evidence/native-refresh'
OUT.mkdir(exist_ok=True)
ACCEPT=','.join(('application/vnd.oci.image.index.v1+json','application/vnd.docker.distribution.manifest.list.v2+json','application/vnd.oci.image.manifest.v1+json','application/vnd.docker.distribution.manifest.v2+json'))
TARGETS={
 'python':('library/python','3.12-alpine'),
 'node':('library/node','22-alpine'),
 'redis':('library/redis','8.2-alpine'),
 'postgres':('library/postgres','18-alpine'),
 'gateway-legacy-full':('nginxinc/nginx-unprivileged','stable-alpine'),
 'gateway-legacy-slim':('nginxinc/nginx-unprivileged','stable-alpine-slim'),
 'gateway-current-full':('nginx/nginx-unprivileged','stable-alpine'),
 'gateway-current-slim':('nginx/nginx-unprivileged','stable-alpine-slim'),
}
TOKENS={}
def token(repo):
 if repo not in TOKENS:
  TOKENS[repo]=json.load(urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io&scope=repository:'+repo+':pull',timeout=30))['token']
 return TOKENS[repo]
def request(repo,kind,ref):
 return urllib.request.Request('https://registry-1.docker.io/v2/'+repo+'/'+kind+'/'+ref,headers={'Authorization':'Bearer '+token(repo),'Accept':ACCEPT} if kind=='manifests' else {'Authorization':'Bearer '+token(repo)})
def document(repo,kind,ref):
 with urllib.request.urlopen(request(repo,kind,ref),timeout=40) as response:
  raw=response.read();digest='sha256:'+hashlib.sha256(raw).hexdigest();header=response.headers.get('Docker-Content-Digest')
  if ref.startswith('sha256:'):assert ref==digest,(kind,ref,digest)
  if header:assert header==digest,(kind,header,digest)
  return json.loads(raw),digest

def metadata(name,target):
 repo,tag=target;folder=OUT/name;folder.mkdir(exist_ok=True)
 try:
  index,digest=document(repo,'manifests',tag)
  if 'manifests' in index:
   selected=next(item for item in index['manifests'] if item['platform']['os']=='linux' and item['platform']['architecture']=='amd64')
   manifest,platform_digest=document(repo,'manifests',selected['digest'])
  else:manifest=index;platform_digest=digest
  config,config_digest=document(repo,'blobs',manifest['config']['digest'])
  record=dict(name=name,repository=repo,tag=tag,registry_url='https://registry-1.docker.io/v2/'+repo,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),index_digest=digest,platform_digest=platform_digest,config_digest=config_digest,compressed_layer_bytes=sum(layer['size'] for layer in manifest['layers']),layers=manifest['layers'],created=config.get('created'),runtime_config={key:config.get('config',{}).get(key) for key in ('User','Entrypoint','Cmd','ExposedPorts')},version_environment=[value for value in config.get('config',{}).get('Env',[]) if value.startswith(('PYTHON_VERSION=','NODE_VERSION=','REDIS_VERSION=','PG_VERSION=','NGINX_VERSION='))])
  for filename,data in (('index.json',index),('manifest.json',manifest),('config.json',config),('metadata.json',record)):(folder/filename).write_text(json.dumps(data,indent=2))
  print(json.dumps({k:record[k] for k in ('name','index_digest','platform_digest','compressed_layer_bytes','created','version_environment')}),flush=True)
  return record
 except Exception as error:
  record=dict(name=name,repository=repo,tag=tag,error=type(error).__name__+': '+str(error));(folder/'error.json').write_text(json.dumps(record,indent=2));print(json.dumps(record),flush=True);return record

class DigestStream:
 def __init__(self,stream):self.stream=stream;self.hash=hashlib.sha256();self.count=0
 def read(self,size=-1):
  data=self.stream.read(size);self.hash.update(data);self.count+=len(data);return data

# Metadata is saved first; inventories can then be streamed without retaining blobs.
def inventory(record):
 if 'error' in record:return record
 repo=record['repository'];folder=OUT/record['name'];files={};layer_evidence=[]
 wanted={'etc/alpine-release','lib/apk/db/installed','usr/lib/apk/db/installed','var/lib/dpkg/status','etc/os-release','usr/lib/os-release'}
 try:
  for layer in record['layers']:
   started=datetime.datetime.now(datetime.timezone.utc).isoformat();updates=[]
   with urllib.request.urlopen(request(repo,'blobs',layer['digest']),timeout=90) as response:
    stream=DigestStream(response)
    with tarfile.open(fileobj=stream,mode='r|*') as archive:
     for member in archive:
      path=member.name
      while path.startswith('./'):path=path[2:]
      path=path.lstrip('/')
      wanted_elf=(path.startswith('usr/local/lib/python3.12/lib-dynload/pyexpat.') and path.endswith('.so')) or (path.startswith('usr/lib/libz.so.') and member.isfile())
      if (path in wanted or wanted_elf) and member.isfile():
       assert member.size<16*1024*1024,(path,member.size)
       data=archive.extractfile(member).read();files[path]=data;updates.append(dict(path=path,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
      if '/.wh.' in path or path.startswith('.wh.'):
       parent,_,leaf=path.rpartition('/')
       if leaf=='.wh..wh..opq':
        for key in list(files):
         if not parent or key.startswith(parent+'/'):files.pop(key)
       elif leaf.startswith('.wh.'):
        removed=(parent+'/' if parent else '')+leaf[4:]
        for key in list(files):
         if key==removed or key.startswith(removed+'/'):files.pop(key)
    while stream.read(1024*1024):pass
    actual='sha256:'+stream.hash.hexdigest();assert actual==layer['digest'],(layer['digest'],actual)
    assert stream.count==layer['size'],(stream.count,layer['size'])
    layer_evidence.append(dict(digest=actual,compressed_bytes=stream.count,verified=True,metadata_updates=updates,started_at=started,finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat()))
   (folder/'layer-stream-progress.json').write_text(json.dumps(layer_evidence,indent=2))
  for name,data in files.items():(folder/('rootfs-'+name.replace('/','_'))).write_bytes(data)
  raw=files.get('lib/apk/db/installed') or files.get('usr/lib/apk/db/installed')
  if raw is None:raise RuntimeError('No APK inventory found; do not classify non-Alpine image with Alpine secdb.')
  packages=[]
  for section in raw.decode().split('\n\n'):
   fields={line[:1]:line[2:] for line in section.splitlines() if len(line)>1 and line[1]==':' and line[0] in 'PVo'}
   if 'P' in fields:packages.append(dict(name=fields['P'],version=fields['V'],origin=fields.get('o',fields['P'])))
  release=files.get('etc/alpine-release',b'').decode().strip()
  result=dict(name=record['name'],repository=repo,tag=record['tag'],index_digest=record['index_digest'],platform_digest=record['platform_digest'],alpine_release=release,packages=packages,package_count=len(packages),layer_digests_verified=True,compressed_bytes_streamed=sum(e['compressed_bytes'] for e in layer_evidence),filesystem_extraction='metadata members only; OCI whiteouts applied bottom-to-top; no Docker image pull/runtime',observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
  (folder/'inventory.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(name=record['name'],alpine=release,packages=len(packages),inventory='PASS',bytes_streamed=result['compressed_bytes_streamed'])),flush=True);return result
 except Exception as error:
  result=dict(name=record['name'],error=type(error).__name__+': '+str(error),verified_layers=len(layer_evidence));(folder/'inventory-error.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True);return result

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--metadata-only',action='store_true');parser.add_argument('--names',nargs='*');args=parser.parse_args()
 chosen={name:value for name,value in TARGETS.items() if not args.names or name in args.names}
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:records=list(pool.map(lambda item:metadata(*item),chosen.items()))
 (OUT/'registry-metadata.json').write_text(json.dumps(records,indent=2))
 if not args.metadata_only:
  # Only two streams at a time; memory and disk usage stay bounded.
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:inventories=list(pool.map(inventory,records))
  (OUT/'inventories.json').write_text(json.dumps(inventories,indent=2))

"""Merge exact-source process coverage, excluding the superseded dispatch module."""
import hashlib,json,shutil,tempfile
from pathlib import Path
import coverage
root=Path(__file__).resolve().parents[2];folder=root/'qa-reports/coverage';inputs=folder/'final-data'
old=json.loads((folder/'final-containers.json').read_text());new=json.loads((folder/'dispatch-containers.json').read_text())
old_hosts=set(old['containers'])|{'ut-qa-final-units'};new_hosts=set(new['containers'])|{'ut-qa-dispatch-fixed-units'}
changed=set(json.loads((root/'qa-reports/evidence/final-source-manifest.json').read_text())['changed_from_interim'])
def read_input(path):
 # Read owned copies: coverage can initialize empty shutdown files on read.
 # Preserve raw process evidence and its ownership/content unchanged.
 with tempfile.TemporaryDirectory(prefix='ut-qa-coverage-read-') as directory:
  local=Path(directory)/'input';shutil.copyfile(path,local)
  source=coverage.CoverageData(basename=str(local));source.read()
  return {filename:source.arcs(filename) for filename in source.measured_files()}
combined=coverage.CoverageData(basename=str(folder/'.coverage'));combined.erase();selected=[];ignored=[]
for path in sorted(inputs.glob('.coverage.*')):
 name=path.name;version='final' if any(name.startswith('.coverage.'+host+'.') for host in new_hosts) else 'interim' if any(name.startswith('.coverage.'+host+'.') for host in old_hosts) else None
 if version is None:ignored.append(name);continue
 measured_files=read_input(path);arcs={};empty=[]
 for filename,measured in measured_files.items():
  if not filename.startswith('/app/app/'):continue
  relative=filename.removeprefix('/app/app/')
  if version=='interim' and relative in changed:continue
  mapped=str(root/'backend/app'/relative)
  if measured:arcs[mapped]=measured
  else:empty.append(mapped)
 if arcs:combined.add_arcs(arcs)
 if empty:combined.touch_files(empty)
 selected.append(dict(file=name,source_version=version,empty_dataset=not measured_files,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
combined.write()
cov=coverage.Coverage(data_file=str(folder/'.coverage'),config_file=False,source=[str(root/'backend/app')],branch=True)
cov.load();cov.json_report(outfile=str(folder/'coverage.json'),pretty_print=True)
with (folder/'coverage.txt').open('w') as stream:cov.report(file=stream,show_missing=True)
(folder/'inputs.json').write_text(json.dumps(dict(interim_image=old['image'],final_image=new['image'],excluded_interim_modules=sorted(changed),selected=selected,ignored=ignored,limits='Celery prefork children may not flush; SQL and frontend TSX branch coverage not measured.'),indent=2)+'\n')
report=json.loads((folder/'coverage.json').read_text());print(json.dumps(report['totals'],indent=2));print('Selected process files:',len(selected),'ignored old/harness files:',len(ignored))

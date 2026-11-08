"""Generate exactly 100k deterministic synthetic valid rows at the 10MiB bound."""
import csv,io,json,hashlib
from pathlib import Path
ROWS=100000;MAX_BYTES=10*1024*1024
AREAS=('416','514','613','604','403','780','204','902','506','709')
HEADERS=('telephone','prenom','nom','nomcomplet','courriel','adresse','ville','province','codepostal')
def line(index,padding=''):
 fields=('1'+AREAS[index//10000]+'555'+f'{index%10000:04d}',f'P{index:06d}',f'N{index:06d}',f'C{index:06d}',f'{index:06d}@example.test',f'Rue{index:06d}'+padding,'Quebec','QC','H2X 1Y4')
 out=io.StringIO();csv.writer(out,lineterminator='\n').writerow(fields)
 return out.getvalue().encode()
out=io.StringIO();csv.writer(out,lineterminator='\n').writerow(HEADERS);header=out.getvalue().encode()
base=len(line(0));remaining=MAX_BYTES-len(header)-ROWS*base
assert remaining>=0
padding,remainder=divmod(remaining,ROWS)
path=Path('/tmp/ut-qa-csv-capacity/near-cap.csv')
with path.open('wb') as stream:
 stream.write(header)
 for index in range(ROWS):stream.write(line(index,'X'*(padding+(index<remainder))))
assert path.stat().st_size==MAX_BYTES
metadata=dict(rows=ROWS,bytes=path.stat().st_size,max_bytes=MAX_BYTES,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),header=HEADERS,mapping=dict(zip(('phone','first_name','last_name','display_name','email','address','city','province','postal_code'),HEADERS)),outside_container_generation=True,synthetic=True,normalization_only_no_dialing=True)
Path('/home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/backend/csv-capacity-fixture.json').write_text(json.dumps(metadata,indent=2))
print(json.dumps(metadata))

"""Reproducible source inventory, not an assertion that each route was tested."""
import ast,json,re
from pathlib import Path
root=Path(__file__).resolve().parents[2];routes=[]
for path in (root/'backend/app').rglob('*.py'):
 try:tree=ast.parse(path.read_text())
 except SyntaxError:continue
 prefixes={}
 for node in ast.walk(tree):
  if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call) and getattr(node.value.func,'id','')=='APIRouter':
   prefix=next((kw.value.value for kw in node.value.keywords if kw.arg=='prefix' and isinstance(kw.value,ast.Constant)),'')
   for target in node.targets:
    if isinstance(target,ast.Name):prefixes[target.id]=prefix
 for node in ast.walk(tree):
  if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
  for decorator in node.decorator_list:
   if not isinstance(decorator,ast.Call) or not isinstance(decorator.func,ast.Attribute) or decorator.func.attr not in ('get','post','patch','put','delete','head','options'):continue
   route=decorator.args[0].value if decorator.args and isinstance(decorator.args[0],ast.Constant) else '[dynamic]'
   prefix=prefixes.get(getattr(decorator.func.value,'id',''),'')
   routes.append(dict(method=decorator.func.attr.upper(),path=prefix+route,source=str(path.relative_to(root)),line=node.lineno,handler=node.name))
report={'definition_count':len(routes),'warning':'Declarations only: mounted routes and method dispatch may differ. No per-route PASS inferred.','routes':sorted(routes,key=lambda x:(x['path'],x['method']))}
(root/'qa-reports/evidence/route-inventory.json').write_text(json.dumps(report,indent=2)+'\n')
print(len(routes),'decorated route declarations inventoried')

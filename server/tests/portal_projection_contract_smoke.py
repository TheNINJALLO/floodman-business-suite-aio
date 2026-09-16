"""Exercise projection/queue compatibility without a live database or providers."""
from __future__ import annotations
import ast
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

def function(path, name, namespace):
    tree=ast.parse(path.read_text(encoding='utf-8'))
    node=next(item for item in ast.walk(tree) if isinstance(item,ast.FunctionDef) and item.name==name)
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(path),'exec'),namespace)
    return namespace[name]

def run():
    saved=[]
    connection=SimpleNamespace(execute=lambda statement,params: saved.append(params) or params)
    update=function(ROOT/'orchestrator/app/repository.py','update_call_projection',{'text':lambda value:value,'_row':lambda row:row,'_json':json.dumps})
    for office_status,sql_status,projection in [('PENDING_APPROVAL','PENDING','PENDING'),('APPROVED','PROJECTED','PROJECTED'),('REVIEW_REQUIRED','REVIEW_REQUIRED','REVIEW_REQUIRED')]:
        update(connection,'fictional-intake',{'review_status':office_status,'projection_status':projection})
        assert saved[-1]['review_status']==sql_status and saved[-1]['projection_status']==projection
    queue=[]
    intake={'caller':{'name':'Test','email':'test@example.test','phone':'+12315550123'},'property':dict.fromkeys(('street','city','state','postal_code'),'Fictional')}
    project=function(ROOT/'orchestrator/app/service.py','project_call_intake_to_office',{'transaction':lambda:nullcontext(connection),'update_call_projection':lambda *args:intake,'enqueue':lambda *args,**kwargs:queue.append(args)})
    for status,approval,expected in [('PENDING','PENDING',0),('PROJECTED','APPROVED',0),('PROJECTED','',1)]:
        result={'projection_status':status,'approval_status':approval,'customer_id':'test-customer','property_id':'test-property'}
        service=SimpleNamespace(office=SimpleNamespace(project_call_intake=lambda payload:result))
        queue.clear()
        project(service,'test-intake',{})
        assert len(queue)==expected
    print('Projection SQL statuses and single-owner ERP synchronization passed; no migration needed')

if __name__=='__main__':run()

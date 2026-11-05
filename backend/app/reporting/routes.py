"""Private administrator reports; aggregations and downloads share definitions."""
from datetime import date
from uuid import UUID
from threading import BoundedSemaphore
import re,unicodedata
from fastapi import APIRouter,Request,Query,HTTPException
from fastapi.responses import Response
from app.identity import service as identity
from app.identity.routes import same_origin
from app.reporting import service
from app.reporting.excel import workbook
from app.telephony import number_health

router=APIRouter(prefix='/api/reporting',tags=['Tableau de bord'])
export_slots=BoundedSemaphore(1)
report_slots=BoundedSemaphore(1)
REPORT_QUEUE_SECONDS=15

@router.post('/presence')
def presence(request:Request):
    same_origin(request)
    with request.app.state.engine.begin() as db:
        identity.authenticate(db,request)
    return {'ok':True}

@router.get('/live')
def live(request:Request):
    with request.app.state.engine.begin() as db:
        identity.admin(db,request)
        result=service.live(db)
        profile=getattr(request.app.state,'voice_profile',None)
        result['directory_warning']=number_health.status(db,profile.account_sid if profile else None)
        return result

def administrator(request):
    # Authentication locks are short. Never retain the actor/global admin lock
    # while a three-month aggregation occupies a database connection.
    with request.app.state.engine.begin() as db:
        identity.admin(db,request)


def aggregate(request,period,agent_id):
    period.bounds()
    # Queue before acquiring SQL: at most one expensive report occupies the
    # two-connection runtime pool. Calls retain a connection of their own.
    if not report_slots.acquire(timeout=REPORT_QUEUE_SECONDS):
        raise HTTPException(429,'Un rapport est déjà en préparation. Réessayez dans quelques secondes.',
                            headers={'Retry-After':'5'})
    try:
        with request.app.state.engine.begin() as db:
            identity.query(db,'SET TRANSACTION READ ONLY')
            return service.report(db,period,agent_id)
    finally:
        report_slots.release()


@router.get('/report')
def report(request:Request,start:date,end:date,timezone:str=Query(default='America/Toronto',max_length=80),agent_id:UUID|None=None):
    administrator(request)
    data=aggregate(request,service.Period(start,end,timezone),agent_id)
    administrator(request)  # Revocation during a long calculation wins.
    return data

@router.get('/export.xlsx')
def export(request:Request,start:date,end:date,timezone:str=Query(default='America/Toronto',max_length=80),agent_id:UUID|None=None):
    administrator(request)
    if not export_slots.acquire(blocking=False):
        raise HTTPException(429,'Un export est déjà en préparation. Réessayez dans un instant.')
    try:
        data=aggregate(request,service.Period(start,end,timezone),agent_id)
        with request.app.state.engine.begin() as db:
            actor=identity.admin(db,request)
            identity.audit(db,actor['id'],'report.export_requested',agent_id)
        # XLSX generation never holds a PostgreSQL connection.
        content=workbook(data)
        agent_name=data['agents'][0]['display_name'] if agent_id else 'equipe'
        slug=re.sub('[^a-z0-9]+','-',unicodedata.normalize('NFKD',agent_name).encode('ascii','ignore').decode().lower()).strip('-')[:40] or 'agent'
        filename=f'unlimited-talk-{slug}{"-"+str(agent_id)[:8] if agent_id else ""}-{start}-{end}.xlsx'
        return Response(content,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={
            'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store',
            'X-Content-Type-Options':'nosniff'})
    finally:
        export_slots.release()

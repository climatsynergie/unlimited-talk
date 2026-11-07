"""Authenticated private audio playback; no provider credentials or redirects."""
import re
from threading import BoundedSemaphore, Lock
from uuid import UUID
from typing import Literal
from fastapi import APIRouter,HTTPException,Request,Query
from pydantic import AwareDatetime
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from app.identity import service as identity
from app.identity.service import query
from app.telephony import archive_storage
from app.telephony.twilio_voice import sid

router=APIRouter(prefix='/api/telephony',tags=['Enregistrements'])
# Bounded streaming, not whole-file buffering: twenty agents plus supervisors.
playback_slots=BoundedSemaphore(24)


@router.get('/calls')
def calls(request:Request,before_created_at:AwareDatetime|None=None,before_id:UUID|None=None,
          q:str=Query(default='',max_length=120),outcome:Literal['','completed','no-answer','busy','failed','canceled']='',
          recordings_only:bool=False,actor_id:UUID|None=None,destination:str=Query(default='',max_length=16),
          from_at:AwareDatetime|None=None,until_at:AwareDatetime|None=None):
    if (before_created_at is None)!=(before_id is None):
        raise HTTPException(400,'Curseur d’historique incomplet.')
    if from_at and until_at and until_at<=from_at:raise HTTPException(400,'La date de fin doit suivre la date de début.')
    if destination and not re.fullmatch(r'\+[1-9][0-9]{8,14}',destination):raise HTTPException(400,'Numéro international invalide.')
    search=q.strip()
    if search and all(c in '+0123456789 ().-' for c in search):search=re.sub(r'[ ().-]','',search)
    search='%'+search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    with request.app.state.engine.begin() as db:
        user=identity.authenticate(db,request)
        if actor_id and user['role']!='admin' and actor_id!=user['id']:raise HTTPException(403,'Vous pouvez consulter uniquement vos appels.')
        rows=query(db,'''SELECT i.id,i.created_at,i.finished_at,i.destination,i.state,i.outcome,i.caller_number,
            i.actor_id,i.campaign_id,i.contact_id,u.display_name AS actor_name,ca.name AS campaign_name,
            coalesce(nullif(trim(c.profile->>'display_name'),''),nullif(trim(concat_ws(' ',c.profile->>'first_name',c.profile->>'last_name')),'')) AS contact_name
            FROM staging.voice_intents i JOIN staging.identity_users u ON u.id=i.actor_id
            LEFT JOIN staging.campaigns ca ON ca.id=i.campaign_id LEFT JOIN staging.contacts c ON c.id=i.contact_id
            WHERE (:admin OR i.actor_id=:actor)
              AND (CAST(:agent AS uuid) IS NULL OR i.actor_id=CAST(:agent AS uuid))
              AND (:destination='' OR i.destination=:destination)
              AND (:outcome='' OR i.outcome=:outcome)
              AND (NOT :recordings OR EXISTS(SELECT 1 FROM staging.voice_recordings r WHERE r.intent_id=i.id))
              AND (CAST(:from_at AS timestamptz) IS NULL OR i.created_at>=CAST(:from_at AS timestamptz))
              AND (CAST(:until_at AS timestamptz) IS NULL OR i.created_at<CAST(:until_at AS timestamptz))
              AND (i.destination ILIKE :search OR u.display_name ILIKE :search OR ca.name ILIKE :search OR c.profile->>'display_name' ILIKE :search
                   OR concat_ws(' ',c.profile->>'first_name',c.profile->>'last_name') ILIKE :search)
              AND
              (:initial OR (i.created_at,i.id)<(CAST(:before_at AS timestamptz),CAST(:before_id AS uuid)))
            ORDER BY i.created_at DESC,i.id DESC LIMIT 21''',admin=user['role']=='admin',actor=user['id'],
            initial=before_id is None,before_at=before_created_at,before_id=before_id,
            agent=actor_id,destination=destination,outcome=outcome,recordings=recordings_only,from_at=from_at,until_at=until_at,search=search).mappings().all()
        items=[dict(row) for row in rows[:20]]
        recordings=[]
        if items:
            recordings=query(db,'''SELECT r.sid,r.intent_id,r.state,r.duration,r.channels,j.archived_at,j.content_bytes,j.last_error_code,j.lease_until
                FROM staging.voice_recordings r LEFT JOIN staging.voice_archive_jobs j ON j.recording_sid=r.sid
                WHERE r.intent_id=ANY(CAST(:ids AS uuid[])) ORDER BY r.created_at,r.sid''',
                ids=[str(item['id']) for item in items]).mappings().all()
        for item in items:
            item['recordings']=[{'sid':r['sid'],'state':r['state'],'duration':r['duration'],
                'channels':r['channels'],'archived_at':r['archived_at'],
                'archive_status':'archived' if r['state']=='archived' else 'retrying'
                    if r['last_error_code'] and r['lease_until'] is None else 'pending',
                'playback_path':'/api/telephony/recordings/'+r['sid']+'/audio'
                    if r['state']=='archived' and r['content_bytes'] is not None else None}
                for r in recordings if r['intent_id']==item['id']]
        cursor={'id':str(items[-1]['id']),'created_at':items[-1]['created_at'].isoformat()} if len(rows)>20 else None
        return {'items':items,'next_cursor':cursor}


@router.get('/call-agents')
def call_agents(request:Request):
    with request.app.state.engine.begin() as db:
        user=identity.admin(db,request)
        rows=query(db,'''SELECT u.id,u.display_name FROM staging.identity_users u
            WHERE (u.role='agent' AND u.is_active) OR EXISTS(SELECT 1 FROM staging.voice_intents i WHERE i.actor_id=u.id)
            ORDER BY lower(u.display_name),u.id LIMIT 1000''').mappings().all()
        return {'items':[dict(row) for row in rows]}


def authorize(request,recording_sid):
    if not sid(recording_sid,'RE'):
        raise HTTPException(404,'Enregistrement introuvable.')
    with request.app.state.engine.begin() as db:
        user=identity.authenticate(db,request)
        row=query(db,'''SELECT r.*,j.content_bytes,j.sample_rate,i.actor_id
            FROM staging.voice_recordings r JOIN staging.voice_intents i ON i.id=r.intent_id
            LEFT JOIN staging.voice_archive_jobs j ON j.recording_sid=r.sid
            WHERE r.sid=:sid''',sid=recording_sid).mappings().first()
        if row is not None and user['role']!='admin' and row['actor_id']!=user['id']:
            raise HTTPException(404,'Enregistrement introuvable.')
        if row is None:
            from app.telephony.incoming_schema import installed
            if installed(db):
                row=query(db,'''SELECT r.*,r.call_id AS intent_id,j.content_bytes,j.sample_rate,c.agent_id AS actor_id
                    FROM staging.inbound_recordings r JOIN staging.inbound_calls c ON c.id=r.call_id
                    LEFT JOIN staging.inbound_archive_jobs j ON j.recording_sid=r.sid
                    WHERE r.sid=:sid AND (:admin OR c.agent_id=:actor OR EXISTS(SELECT 1 FROM staging.inbound_queue_agents a
                        WHERE a.queue_id=c.queue_id AND a.user_id=:actor AND a.is_active))''',
                    sid=recording_sid,admin=user['role']=='admin',actor=user['id']).mappings().first()
            if row is None:raise HTTPException(404,'Enregistrement introuvable.')
        if row['state']!='archived' or row['content_bytes'] is None:
            raise HTTPException(409,'La sauvegarde de cet enregistrement est en cours. Réessayez dans un instant.')
        if row['object_key']!=archive_storage.object_key(row['intent_id'],row['sid'],row['checksum']):
            raise HTTPException(503,'La lecture est temporairement indisponible.')
        identity.audit(db,user['id'],'voice.recording_requested',row['intent_id'])
        return dict(row)


def byte_range(value,size):
    if value is None:return 0,size-1,200
    match=re.fullmatch(r'bytes=([0-9]{0,10})-([0-9]{0,10})',value)
    if match and any(match.groups()):
        first,last=match.groups()
        if not first:
            length=int(last)
            if length>0:return max(0,size-length),size-1,206
        else:
            start=int(first);end=min(size-1,int(last)) if last else size-1
            if 0<=start<=end and start<size:return start,end,206
    raise HTTPException(416,'Plage audio invalide.',headers={'Content-Range':f'bytes */{size}'})


@router.get('/recordings/{recording_sid}/audio')
async def audio(recording_sid:str,request:Request):
    row=await run_in_threadpool(authorize,request,recording_sid)
    if len(request.headers.getlist('range'))>1:
        raise HTTPException(416,'Plage audio invalide.')
    start,end,status=byte_range(request.headers.get('range'),row['content_bytes'])
    if not playback_slots.acquire(blocking=False):
        raise HTTPException(429,'Les chargements audio sont occupés. Réessayez dans un instant.',headers={'Retry-After':'2'})
    try:
        chunks,close=await run_in_threadpool(archive_storage.open_range,
            row['object_key'],row['checksum'],row['content_bytes'],start,end)
    except Exception:
        playback_slots.release()
        raise HTTPException(503,'La lecture est temporairement indisponible. Réessayez dans un instant.') from None
    closed=False
    lock=Lock()
    def cleanup():
        nonlocal closed
        with lock:
            if closed:return
            closed=True
            try:close()
            finally:playback_slots.release()
    def stream():
        try:yield from chunks
        finally:cleanup()
    headers={'Accept-Ranges':'bytes','Content-Disposition':'inline; filename="enregistrement.wav"',
             'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Length':str(end-start+1)}
    if status==206:headers['Content-Range']=f'bytes {start}-{end}/{row["content_bytes"]}'
    return StreamingResponse(stream(),status_code=status,media_type='audio/wav',headers=headers,
                             background=BackgroundTask(cleanup))

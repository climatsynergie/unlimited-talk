"""Authenticated private audio playback; no provider credentials or redirects."""
import re
from threading import BoundedSemaphore
from uuid import UUID
from fastapi import APIRouter,HTTPException,Request
from pydantic import AwareDatetime
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from app.identity import service as identity
from app.identity.service import query
from app.telephony import archive_storage
from app.telephony.twilio_voice import sid

router=APIRouter(prefix='/api/telephony',tags=['Enregistrements'])
playback_slots=BoundedSemaphore(2)


@router.get('/calls')
def calls(request:Request,before_created_at:AwareDatetime|None=None,before_id:UUID|None=None):
    if (before_created_at is None)!=(before_id is None):
        raise HTTPException(400,'Curseur d’historique incomplet.')
    with request.app.state.engine.begin() as db:
        user=identity.authenticate(db,request)
        rows=query(db,'''SELECT i.id,i.created_at,i.destination,i.state,i.outcome,u.display_name AS actor_name
            FROM staging.voice_intents i JOIN staging.identity_users u ON u.id=i.actor_id
            WHERE (:admin OR i.actor_id=:actor) AND
              (:initial OR (i.created_at,i.id)<(CAST(:before_at AS timestamptz),CAST(:before_id AS uuid)))
            ORDER BY i.created_at DESC,i.id DESC LIMIT 21''',admin=user['role']=='admin',actor=user['id'],
            initial=before_id is None,before_at=before_created_at,before_id=before_id).mappings().all()
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


def authorize(request,recording_sid):
    if not sid(recording_sid,'RE'):
        raise HTTPException(404,'Enregistrement introuvable.')
    with request.app.state.engine.begin() as db:
        user=identity.authenticate(db,request)
        row=query(db,'''SELECT r.*,j.content_bytes,j.sample_rate,i.actor_id
            FROM staging.voice_recordings r JOIN staging.voice_intents i ON i.id=r.intent_id
            LEFT JOIN staging.voice_archive_jobs j ON j.recording_sid=r.sid
            WHERE r.sid=:sid''',sid=recording_sid).mappings().first()
        if row is None or (user['role']!='admin' and row['actor_id']!=user['id']):
            raise HTTPException(404,'Enregistrement introuvable.')
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
        raise HTTPException(429,'Deux lectures audio sont déjà en cours. Réessayez dans un instant.')
    try:
        try:
            content=await run_in_threadpool(archive_storage.read,row['object_key'],row['checksum'],row['content_bytes'])
        except Exception:
            raise HTTPException(503,'La lecture est temporairement indisponible. Réessayez dans un instant.') from None
        headers={'Accept-Ranges':'bytes','Content-Disposition':'inline; filename="enregistrement.wav"',
                 'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}
        if status==206:headers['Content-Range']=f'bytes {start}-{end}/{len(content)}'
        return Response(content[start:end+1],status_code=status,media_type='audio/wav',headers=headers)
    finally:
        playback_slots.release()

"""Bounded incoming history and private recording metadata, scoped to queue membership."""
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request
from app.identity.routes import same_origin
from app.identity.service import authenticate,query
from app.telephony.inbound_service import queue
from app.telephony.incoming_schema import installed

router=APIRouter(prefix='/api/inbound',dependencies=[Depends(same_origin)])


def recordings(db,ids):
    if not ids:return []
    return query(db,'''SELECT r.sid,r.call_id,r.kind,r.duration,r.channels,r.state,j.archived_at
        FROM staging.inbound_recordings r LEFT JOIN staging.inbound_archive_jobs j ON j.recording_sid=r.sid
        WHERE r.call_id=ANY(CAST(:ids AS uuid[])) ORDER BY r.created_at,r.sid''',ids=[str(value) for value in ids]).mappings().all()


@router.get('/queues/{identifier}/calls')
def listing(identifier:UUID,request:Request,before:UUID|None=None):
    with request.app.state.engine.begin() as db:
        actor=authenticate(db,request);queue(db,actor,identifier)
        if not installed(db):return {'items':[],'has_more':False}
        cursor=None
        if before:
            cursor=query(db,'SELECT received_at FROM staging.inbound_calls WHERE queue_id=:queue AND id=:id',queue=identifier,id=before).scalar_one_or_none()
            if cursor is None:raise HTTPException(400,'Position d’historique invalide.')
        rows=query(db,'''SELECT c.id,c.received_at,c.connected_at,c.finished_at,c.caller_number,c.called_number,c.state,c.outcome,c.followup_id,
            c.agent_id,u.display_name AS agent_name,p.profile,p.id AS contact_id FROM staging.inbound_calls c
            LEFT JOIN staging.identity_users u ON u.id=c.agent_id LEFT JOIN staging.contacts p ON p.phone=c.caller_number
            WHERE c.queue_id=:queue AND (CAST(:before AS uuid) IS NULL OR (c.received_at,c.id)<(CAST(:stamp AS timestamptz),CAST(:before AS uuid)))
            ORDER BY c.received_at DESC,c.id DESC LIMIT 21''',queue=identifier,before=before,stamp=cursor).mappings().all()
        media=recordings(db,[row['id'] for row in rows[:20]])
        return {'items':[{**row,'recordings':[{key:value for key,value in recording.items() if key!='call_id'}
            for recording in media if recording['call_id']==row['id']]} for row in rows[:20]],'has_more':len(rows)>20}

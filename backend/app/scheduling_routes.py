"""Shared local-time resolution for calendars and callback schedules."""
from fastapi import APIRouter,Depends,Query,Request
from pydantic import NaiveDatetime
from app.identity.routes import same_origin
from app.identity.service import authenticate
from app.scheduling_time import possibilities
router=APIRouter(prefix='/api/scheduling',tags=['Scheduling'],dependencies=[Depends(same_origin)])


@router.get('/resolve')
def local_time(request:Request,local_start:NaiveDatetime,timezone:str=Query(max_length=80)):
    with request.app.state.engine.begin() as db:
        authenticate(db,request)
        return {'options':possibilities(local_start,timezone)}

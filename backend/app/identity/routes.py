"""Cookie-based browser API; never return password hashes or session hashes."""
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator

from app.identity import service
from app.identity.security import COOKIE, CSRF_COOKIE, email_address, digest


def same_origin(request: Request):
    if request.method not in {'GET','HEAD','OPTIONS'} and request.headers.get('origin') != request.app.state.identity_origin:
        raise HTTPException(403,'Origine de requête invalide')


router = APIRouter(prefix='/api',tags=['Identity'],dependencies=[Depends(same_origin)])


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Body):
    email: str = Field(max_length=254)
    password: SecretStr = Field(min_length=1,max_length=128)
    factor: SecretStr = Field(default=SecretStr(''),max_length=64)

    @field_validator('email')
    @classmethod
    def email_normalized(cls,value):
        return email_address(value)


class Invitation(Body):
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=1,max_length=200)
    role: Literal['admin','agent']

    @field_validator('email')
    @classmethod
    def email_normalized(cls,value):
        return email_address(value)

    @field_validator('display_name')
    @classmethod
    def nonblank_name(cls,value):
        if not value.strip():
            raise ValueError('Nom requis')
        return value.strip()


class Acceptance(Body):
    token: SecretStr = Field(min_length=40,max_length=64)
    password: SecretStr = Field(min_length=15,max_length=128)


class Factor(Body):
    code: SecretStr = Field(min_length=6,max_length=64)


class UserUpdate(Body):
    role: Literal['admin','agent'] | None = None
    is_active: StrictBool | None = None


class PasswordChange(Body):
    current_password: SecretStr = Field(min_length=1,max_length=128)
    new_password: SecretStr = Field(min_length=15,max_length=128)
    factor: SecretStr = Field(default=SecretStr(''),max_length=64)


def session_response(result):
    # Tokens are emitted only in secure cookies; JS reads the CSRF cookie.
    payload = {key:value for key,value in result.items() if key not in {'session_token','csrf_token','max_age'}}
    response = JSONResponse(payload)
    for name,value,httponly in [(COOKIE,result['session_token'],True),
                               (CSRF_COOKIE,result['csrf_token'],False)]:
        response.set_cookie(name,value,secure=True,httponly=httponly,samesite='strict',
                            path='/',max_age=result['max_age'])
    return response


@router.post('/auth/login')
def login(body: Login, request: Request):
    return session_response(service.login(request.app.state.engine,body.email,
        body.password.get_secret_value(),body.factor.get_secret_value(),request.app.state.identity_cipher,
        request.cookies.get(COOKIE)))


@router.post('/auth/invitations/accept')
def accept(body: Acceptance, request: Request):
    try:
        result = service.accept_invitation(request.app.state.engine,body.token.get_secret_value(),body.password.get_secret_value())
    except ValueError as error:
        raise HTTPException(400,str(error)) from None
    return session_response(result)


@router.get('/auth/me')
def me(request: Request):
    with request.app.state.engine.begin() as db:
        user = service.authenticate(db,request,enrollment=True)
        return {'user':service.public_user(user),'mfa_enrollment_required':not user['mfa_verified']}


@router.post('/auth/logout')
def logout(request: Request):
    with request.app.state.engine.begin() as db:
        user = service.authenticate(db,request,enrollment=True)
        service.query(db,'DELETE FROM staging.identity_sessions WHERE token_hash=:hash',hash=user['session_hash'])
        service.audit(db,user['id'],'session.logout',user['id'])
    response = JSONResponse({'status':'signed_out'})
    for cookie in [COOKIE,CSRF_COOKIE]:
        response.delete_cookie(cookie,path='/',secure=True,httponly=cookie==COOKIE,samesite='strict')
    return response


@router.post('/auth/logout-all')
def logout_all(request: Request):
    with request.app.state.engine.begin() as db:
        user = service.authenticate(db,request)
        service.query(db,'DELETE FROM staging.identity_sessions WHERE user_id=:id',id=user['id'])
        service.audit(db,user['id'],'session.all_revoked',user['id'])
    response = JSONResponse({'status':'signed_out'})
    for cookie in [COOKIE,CSRF_COOKIE]:
        response.delete_cookie(cookie,path='/',secure=True,httponly=cookie==COOKIE,samesite='strict')
    return response


@router.post('/auth/mfa/enroll')
def mfa_enroll(request: Request):
    service.limited(request.app.state.engine,'mfa',digest(request.cookies.get(COOKIE,'')))
    with request.app.state.engine.begin() as db:
        user = service.authenticate(db,request,enrollment=True,recent=True)
        return service.enroll_start(db,user,request.app.state.identity_cipher)


@router.post('/auth/mfa/confirm')
def mfa_confirm(body: Factor, request: Request):
    service.limited(request.app.state.engine,'mfa',digest(request.cookies.get(COOKIE,'')))
    with request.app.state.engine.begin() as db:
        user = service.authenticate(db,request,enrollment=True,recent=True)
        result = service.enroll_finish(db,user,body.code.get_secret_value(),request.app.state.identity_cipher)
    return session_response(result)


@router.post('/auth/password')
def change_password(body: PasswordChange, request: Request):
    service.limited(request.app.state.engine,'password',digest(request.cookies.get(COOKIE,'')))
    try:
        with request.app.state.engine.begin() as db:
            user = service.authenticate(db,request,recent=True)
            result = service.password_change(db,user,body.current_password.get_secret_value(),
                body.new_password.get_secret_value(),body.factor.get_secret_value(),request.app.state.identity_cipher)
    except ValueError as error:
        raise HTTPException(400,str(error)) from None
    return session_response(result)


@router.get('/admin/users')
def users(request: Request, limit: int = Query(50,ge=1,le=100), offset: int = Query(0,ge=0)):
    with request.app.state.engine.begin() as db:
        service.admin(db,request)
        rows = service.query(db,'''SELECT id,email,display_name,role,is_active FROM staging.identity_users
            ORDER BY created_at,id LIMIT :limit OFFSET :offset''',limit=limit,offset=offset).mappings()
        return {'users':[service.public_user(row) for row in rows]}


@router.patch('/admin/users/{identifier}')
def update_user(identifier: uuid.UUID, body: UserUpdate, request: Request):
    with request.app.state.engine.begin() as db:
        actor = service.admin(db,request)
        return service.update_user(db,actor,identifier,body.role,body.is_active)


@router.post('/admin/users/{identifier}/revoke-sessions')
def revoke_sessions(identifier: uuid.UUID, request: Request):
    with request.app.state.engine.begin() as db:
        actor = service.admin(db,request)
        if not service.query(db,'SELECT id FROM staging.identity_users WHERE id=:id',id=identifier).first():
            raise HTTPException(404,'Compte introuvable')
        service.query(db,'SELECT id FROM staging.identity_users WHERE id=:id FOR UPDATE',id=identifier)
        service.query(db,'DELETE FROM staging.identity_sessions WHERE user_id=:id',id=identifier)
        service.audit(db,actor['id'],'session.admin_revoked',identifier)
    return {'status':'revoked'}


@router.post('/admin/invitations',status_code=201)
def invitation(body: Invitation, request: Request):
    with request.app.state.engine.begin() as db:
        actor = service.admin(db,request)
        return service.issue_invitation(db,actor,body.email,body.display_name,body.role)


@router.get('/admin/invitations')
def invitations(request: Request,limit: int = Query(50,ge=1,le=100),offset: int = Query(0,ge=0)):
    with request.app.state.engine.begin() as db:
        service.admin(db,request)
        rows = service.query(db,'''SELECT id,email,display_name,role,created_at,expires_at,used_at,revoked_at
            FROM staging.identity_invitations ORDER BY created_at DESC,id LIMIT :limit OFFSET :offset''',
            limit=limit,offset=offset).mappings()
        return {'invitations':[{k:str(v) if v is not None else None for k,v in row.items()} for row in rows]}


@router.delete('/admin/invitations/{identifier}')
def revoke_invitation(identifier: uuid.UUID, request: Request):
    with request.app.state.engine.begin() as db:
        actor = service.admin(db,request)
        row = service.query(db,'''UPDATE staging.identity_invitations SET revoked_at=now()
            WHERE id=:id AND used_at IS NULL AND revoked_at IS NULL RETURNING id''',id=identifier).first()
        if not row:
            raise HTTPException(404,'Invitation indisponible')
        service.audit(db,actor['id'],'invitation.revoked',identifier)
    return {'status':'revoked'}


@router.get('/admin/audit')
def audit_events(request: Request,limit: int = Query(50,ge=1,le=100),before: int | None = Query(None,ge=1)):
    with request.app.state.engine.begin() as db:
        service.admin(db,request)
        rows = service.query(db,'''SELECT id,actor_id,action,subject_id,created_at FROM staging.identity_audit
            WHERE (CAST(:before AS bigint) IS NULL OR id<:before) ORDER BY id DESC LIMIT :limit''',before=before,limit=limit).mappings()
        return {'events':[{k:str(v) if v is not None else None for k,v in row.items()} for row in rows]}


class ResetPassword(Acceptance):
    factor: SecretStr = Field(default=SecretStr(''),max_length=64)


@router.post('/admin/users/{identifier}/password-reset')
def issue_reset(identifier: uuid.UUID, request: Request):
    with request.app.state.engine.begin() as db:
        actor = service.admin(db,request)
        return service.issue_password_reset(db,actor,identifier)


@router.post('/auth/password-reset')
def reset_password(body: ResetPassword, request: Request):
    try:
        result = service.reset_password(request.app.state.engine,body.token.get_secret_value(),
            body.password.get_secret_value(),body.factor.get_secret_value(),request.app.state.identity_cipher)
    except ValueError as error:
        raise HTTPException(400,str(error)) from None
    return session_response(result)

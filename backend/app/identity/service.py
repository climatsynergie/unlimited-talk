"""Transactional identity operations; PostgreSQL owns sessions and revocations."""
from datetime import timedelta
import hmac
import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import pyotp

from app.identity.security import (COOKIE, CSRF_COOKIE, ENROLLMENT_SECONDS, IDLE_SECONDS,
                                   PASSWORDS, SESSION_SECONDS, digest, hash_password,
                                   new_token, otp_counter, utcnow, validate_password,
                                   verify_password)

ADMIN_LOCK = 74192001


def query(db, statement, **values):
    return db.execute(text(statement), values)


def audit(db, actor, action, subject=None):
    query(db, 'INSERT INTO staging.identity_audit(actor_id,action,subject_id) VALUES (:actor,:action,:subject)',
          actor=actor, action=action, subject=subject)


def public_user(row):
    return {key: str(row[key]) if key == 'id' else row[key]
            for key in ('id', 'email', 'display_name', 'role', 'is_active')}


def limited(engine, operation, identity):
    """Independent committed counters survive bad-password transaction rollback."""
    exceeded = False
    with engine.begin() as db:
        query(db, 'DELETE FROM staging.identity_rate_limits WHERE expires_at<now()-interval \'1 day\'')
        for bucket, limit, seconds in [('global', 200, 60), (operation + ':' + digest(identity), 10, 900)]:
            row = query(db, '''INSERT INTO staging.identity_rate_limits(bucket,attempts,expires_at)
                VALUES (:bucket,1,now()+make_interval(secs=>:seconds))
                ON CONFLICT(bucket) DO UPDATE SET
                attempts=CASE WHEN identity_rate_limits.expires_at<=now() THEN 1 ELSE identity_rate_limits.attempts+1 END,
                expires_at=CASE WHEN identity_rate_limits.expires_at<=now() THEN excluded.expires_at ELSE identity_rate_limits.expires_at END
                RETURNING attempts''', bucket=bucket, seconds=seconds).scalar_one()
            exceeded |= row > limit
    if exceeded:
        raise HTTPException(429, 'Trop de tentatives. Réessayez plus tard.', headers={'Retry-After': '900'})


def new_session(db, user, verified, previous=None):
    if previous:
        query(db, 'DELETE FROM staging.identity_sessions WHERE token_hash=:token AND user_id=:id', token=previous, id=user['id'])
    query(db, 'DELETE FROM staging.identity_sessions WHERE expires_at<now() OR last_seen_at<now()-interval \'30 minutes\'')
    # Bound the number of simultaneous browsers per user.
    query(db, '''DELETE FROM staging.identity_sessions WHERE token_hash IN (
        SELECT token_hash FROM staging.identity_sessions WHERE user_id=:id
        ORDER BY created_at DESC OFFSET 4)''', id=user['id'])
    token, csrf = new_token(), new_token()
    duration = SESSION_SECONDS if verified else ENROLLMENT_SECONDS
    query(db, '''INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at)
        VALUES (:token,:csrf,:id,:verified,:expiry)''', token=digest(token), csrf=digest(csrf),
          id=user['id'], verified=verified, expiry=utcnow()+timedelta(seconds=duration))
    return {'user': public_user(user), 'mfa_enrollment_required': not verified,
            'session_token': token, 'csrf_token': csrf, 'max_age': duration}


def authenticate(db, request, *, enrollment=False, recent=False, touch=True):
    token = request.cookies.get(COOKIE, '')
    if not 40 <= len(token) <= 64:
        raise HTTPException(401, 'Connexion requise')
    row = query(db, '''SELECT u.*,s.mfa_verified,s.csrf_hash,s.token_hash AS session_hash,
        s.created_at AS authenticated_at FROM staging.identity_sessions s
        JOIN staging.identity_users u ON u.id=s.user_id
        WHERE s.token_hash=:token AND u.is_active AND s.expires_at>now()
          AND s.last_seen_at>now()-interval '30 minutes'
        FOR UPDATE OF u''', token=digest(token)).mappings().first()
    if row is None:
        raise HTTPException(401, 'Connexion requise')
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        csrf = request.headers.get('X-CSRF-Token', '')
        cookie = request.cookies.get(CSRF_COOKIE, '')
        if not csrf or len(csrf)>64 or not hmac.compare_digest(csrf,cookie) or not hmac.compare_digest(digest(csrf),row['csrf_hash']):
            raise HTTPException(403, 'Jeton CSRF invalide')
    if not enrollment and (not row['mfa_verified'] or (row['role']=='admin' and not row['mfa_secret'])):
        raise HTTPException(403, 'Configuration de la double authentification requise')
    if recent and row['authenticated_at'] < utcnow()-timedelta(minutes=15):
        raise HTTPException(403, 'Reconnectez-vous avant cette action sensible')
    statement = ('UPDATE staging.identity_sessions SET last_seen_at=now() WHERE token_hash=:token RETURNING token_hash'
                 if touch else 'SELECT token_hash FROM staging.identity_sessions WHERE token_hash=:token')
    if query(db,statement,token=row['session_hash']).first() is None:
        raise HTTPException(401, 'Connexion requise')
    return row


def admin(db, request):
    # Acquire before any per-user locks to serialize role/last-admin decisions.
    query(db, 'SELECT pg_advisory_xact_lock(:key)', key=ADMIN_LOCK)
    user = authenticate(db, request, recent=request.method!='GET')
    if user['role'] != 'admin':
        raise HTTPException(403, 'Accès administrateur requis')
    return user


def verify_factor(db, user, factor, cipher):
    if not user['mfa_secret']:
        return False
    secret = cipher.decrypt(user['mfa_secret'].encode()).decode()
    counter = otp_counter(secret, factor, user['mfa_last_counter'])
    if counter is not None:
        query(db, 'UPDATE staging.identity_users SET mfa_last_counter=:counter WHERE id=:id',
              counter=counter, id=user['id'])
        return True
    # Recovery values have 192 bits of randomness and are stored only by hash.
    if len(factor) == 32:
        used = query(db, '''UPDATE staging.identity_recovery_codes SET used_at=now()
            WHERE user_id=:id AND code_hash=:hash AND used_at IS NULL RETURNING code_hash''',
                     id=user['id'], hash=digest(factor)).first()
        if used:
            audit(db, user['id'], 'mfa.recovery_used', user['id'])
            return True
    return False


def login(engine, email, password, factor, cipher, previous_token=None):
    limited(engine, 'login', email)
    result = None
    with engine.begin() as db:
        user = query(db, 'SELECT * FROM staging.identity_users WHERE email=:email FOR UPDATE', email=email).mappings().first()
        valid = verify_password(user['password_hash'] if user else None, password)
        if valid and user and user['is_active']:
            valid = not user['mfa_secret'] or verify_factor(db,user,factor,cipher)
            if valid:
                if PASSWORDS.check_needs_rehash(user['password_hash']):
                    query(db, 'UPDATE staging.identity_users SET password_hash=:hash WHERE id=:id',
                          hash=hash_password(password), id=user['id'])
                verified = user['role']!='admin' or bool(user['mfa_secret'])
                result = new_session(db,user,verified,digest(previous_token) if previous_token else None)
                audit(db,user['id'],'session.login',user['id'])
        if result is None:
            audit(db,user['id'] if user else None,'session.login_failed')
    if result is None:
        raise HTTPException(401, 'Identifiants invalides')
    return result


def recovery_codes(db, user_id):
    query(db, 'DELETE FROM staging.identity_recovery_codes WHERE user_id=:id', id=user_id)
    codes = [new_token()[:32] for _ in range(8)]
    for code in codes:
        query(db, 'INSERT INTO staging.identity_recovery_codes(user_id,code_hash) VALUES (:id,:hash)',
              id=user_id, hash=digest(code))
    return codes


def enroll_start(db, user, cipher):
    if user['role']!='admin' or user['mfa_secret']:
        raise HTTPException(409, 'Configuration de la double authentification indisponible')
    secret = pyotp.random_base32()
    query(db, '''UPDATE staging.identity_users SET mfa_pending=:secret,
        mfa_pending_until=now()+interval '10 minutes' WHERE id=:id''',
          secret=cipher.encrypt(secret.encode()).decode(), id=user['id'])
    audit(db,user['id'],'mfa.enrollment_started',user['id'])
    return {'secret': secret, 'provisioning_uri': pyotp.TOTP(secret).provisioning_uri(
        name=user['email'],issuer_name='Unlimited Talks Préproduction')}


def enroll_finish(db, user, code, cipher):
    if user['mfa_secret'] or not user['mfa_pending'] or user['mfa_pending_until']<=utcnow():
        raise HTTPException(400, 'Configuration de la double authentification expirée ou indisponible')
    secret = cipher.decrypt(user['mfa_pending'].encode()).decode()
    counter = otp_counter(secret,code,-1)
    if counter is None:
        raise HTTPException(400, 'Code d’authentification invalide')
    query(db, '''UPDATE staging.identity_users SET mfa_secret=mfa_pending,mfa_pending=NULL,
        mfa_pending_until=NULL,mfa_last_counter=:counter WHERE id=:id''', counter=counter,id=user['id'])
    query(db, 'DELETE FROM staging.identity_sessions WHERE user_id=:id', id=user['id'])
    result = new_session(db,user,True)
    result['recovery_codes'] = recovery_codes(db,user['id'])
    audit(db,user['id'],'mfa.enrolled',user['id'])
    return result


def issue_invitation(db, actor, email, name, role):
    # This operation is serialized by the administrative transaction lock.
    if query(db,'SELECT id FROM staging.identity_users WHERE email=:email',email=email).first():
        raise HTTPException(409,'Ce compte existe déjà')
    query(db, '''UPDATE staging.identity_invitations SET revoked_at=now()
        WHERE email=:email AND used_at IS NULL AND revoked_at IS NULL''',email=email)
    token, identifier = new_token(), uuid.uuid4()
    query(db, '''INSERT INTO staging.identity_invitations(id,token_hash,email,display_name,role,created_by,expires_at)
        VALUES (:id,:hash,:email,:name,:role,:actor,now()+interval '24 hours')''',
          id=identifier,hash=digest(token),email=email,name=name,role=role,actor=actor['id'])
    audit(db,actor['id'],'invitation.created',identifier)
    return {'id':str(identifier),'token':token,'expires_in':86400,'email':email,'role':role}


def accept_invitation(engine, token, password):
    limited(engine,'invitation',digest(token))
    encoded = hash_password(validate_password(password))
    result = None
    try:
        with engine.begin() as db:
            row = query(db, '''SELECT * FROM staging.identity_invitations WHERE token_hash=:hash
                AND used_at IS NULL AND revoked_at IS NULL AND expires_at>now() FOR UPDATE''', hash=digest(token)).mappings().first()
            if row:
                identifier = uuid.uuid4()
                user = query(db, '''INSERT INTO staging.identity_users(id,email,display_name,role,password_hash)
                    VALUES (:id,:email,:name,:role,:hash) RETURNING *''', id=identifier,email=row['email'],
                    name=row['display_name'],role=row['role'],hash=encoded).mappings().one()
                query(db,'UPDATE staging.identity_invitations SET used_at=now() WHERE id=:id',id=row['id'])
                audit(db,identifier,'invitation.accepted',row['id'])
                result = new_session(db,user,user['role']!='admin')
    except IntegrityError:
        result = None
    if result is None:
        raise HTTPException(400,'Invitation invalide ou expirée')
    return result


def update_user(db, actor, identifier, role, active):
    target = query(db,'SELECT * FROM staging.identity_users WHERE id=:id FOR UPDATE',id=identifier).mappings().first()
    if target is None:
        raise HTTPException(404,'Compte introuvable')
    role = role or target['role']
    active = target['is_active'] if active is None else active
    if target['role']=='admin' and target['is_active'] and target['mfa_secret'] and (role!='admin' or not active):
        others = query(db, '''SELECT count(*) FROM staging.identity_users
            WHERE id<>:id AND role='admin' AND is_active AND mfa_secret IS NOT NULL''', id=identifier).scalar_one()
        if others==0:
            raise HTTPException(409,'Le dernier administrateur actif doit être conservé')
    user = query(db, '''UPDATE staging.identity_users SET role=:role,is_active=:active
        WHERE id=:id RETURNING *''',id=identifier,role=role,active=active).mappings().one()
    query(db,'DELETE FROM staging.identity_sessions WHERE user_id=:id',id=identifier)
    audit(db,actor['id'],'user.permissions_changed',identifier)
    return public_user(user)


def password_change(db, user, old_password, new_password, factor, cipher):
    if not verify_password(user['password_hash'],old_password) or (user['mfa_secret'] and not verify_factor(db,user,factor,cipher)):
        raise HTTPException(401,'Identifiants invalides')
    encoded = hash_password(validate_password(new_password))
    query(db,'UPDATE staging.identity_users SET password_hash=:hash WHERE id=:id',hash=encoded,id=user['id'])
    query(db,'DELETE FROM staging.identity_sessions WHERE user_id=:id',id=user['id'])
    audit(db,user['id'],'user.password_changed',user['id'])
    return new_session(db,user,True)


def issue_password_reset(db, actor, identifier):
    user = query(db,'SELECT * FROM staging.identity_users WHERE id=:id FOR UPDATE',id=identifier).mappings().first()
    if not user or not user['is_active']:
        raise HTTPException(404,'Compte actif introuvable')
    token = new_token()
    query(db,'''UPDATE staging.identity_password_resets SET revoked_at=now()
        WHERE user_id=:id AND used_at IS NULL AND revoked_at IS NULL''',id=identifier)
    query(db,'''INSERT INTO staging.identity_password_resets(token_hash,user_id,created_by,expires_at)
        VALUES (:hash,:id,:actor,now()+interval '30 minutes')''',hash=digest(token),id=identifier,actor=actor['id'])
    query(db,'DELETE FROM staging.identity_sessions WHERE user_id=:id',id=identifier)
    audit(db,actor['id'],'user.password_reset_issued',identifier)
    return {'token':token,'expires_in':1800}


def reset_password(engine, token, password, factor, cipher):
    limited(engine,'reset',digest(token))
    encoded = hash_password(validate_password(password))
    result = None
    with engine.begin() as db:
        # Lock users before reset rows, matching all authenticated operations.
        row = query(db,'''SELECT u.*,r.token_hash AS reset_hash FROM staging.identity_users u
            JOIN staging.identity_password_resets r ON r.user_id=u.id
            WHERE r.token_hash=:hash AND r.used_at IS NULL AND r.revoked_at IS NULL
              AND r.expires_at>now() AND u.is_active FOR UPDATE OF u,r''',hash=digest(token)).mappings().first()
        if row and (not row['mfa_secret'] or verify_factor(db,row,factor,cipher)):
            query(db,'UPDATE staging.identity_users SET password_hash=:hash WHERE id=:id',hash=encoded,id=row['id'])
            query(db,'UPDATE staging.identity_password_resets SET used_at=now() WHERE token_hash=:hash',hash=digest(token))
            query(db,'DELETE FROM staging.identity_sessions WHERE user_id=:id',id=row['id'])
            audit(db,row['id'],'user.password_reset_completed',row['id'])
            result = new_session(db,row,row['role']!='admin' or bool(row['mfa_secret']))
    if result is None:
        raise HTTPException(400,'Réinitialisation invalide ou expirée')
    return result

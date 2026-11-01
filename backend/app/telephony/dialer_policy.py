"""Shared calling policy for manual, campaign and scheduled callback calls."""
from datetime import datetime,time,timedelta
from zoneinfo import ZoneInfo
import re
from uuid import UUID

import phonenumbers
from fastapi import HTTPException
from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator
from app.identity.service import query
from app.campaigns import service as campaigns
from app.telephony.inbound_settings import Body,Hours,within_hours


class RegionRule(Body):
    number_id: UUID
    country: str = Field(default='',max_length=2)
    prefix: str = Field(default='',max_length=15)

    @model_validator(mode='after')
    def valid_region(self):
        self.country=self.country.upper().strip()
        self.prefix=self.prefix.strip()
        if (not self.country and not self.prefix) or (self.country and self.country not in phonenumbers.SUPPORTED_REGIONS):
            raise ValueError('Pays ou préfixe requis.')
        if self.prefix and not re.fullmatch(r'\+[1-9][0-9]{0,13}',self.prefix):
            raise ValueError('Préfixe international invalide.')
        return self


class CallingSettings(Body):
    request_id: UUID
    version: StrictInt = Field(ge=0)
    enabled: StrictBool = False
    default_number_id: UUID | None = None
    hours: list[Hours] = Field(default_factory=list,max_length=14)
    rules: list[RegionRule] = Field(default_factory=list,max_length=50)

    @model_validator(mode='after')
    def consistent(self):
        if self.enabled and self.default_number_id is None:
            raise ValueError('Choisissez le numéro émetteur de la campagne.')
        self.hours=sorted(self.hours,key=lambda h:(h.weekday,h.start))
        if any(a.weekday==b.weekday and a.end>b.start for a,b in zip(self.hours,self.hours[1:])):
            raise ValueError('Les horaires se chevauchent.')
        if len({(r.country,r.prefix) for r in self.rules})!=len(self.rules):
            raise ValueError('Règle régionale en double.')
        self.rules=sorted(self.rules,key=lambda r:(r.country,r.prefix))
        return self


def settings(db,campaign_id):
    return query(db,'SELECT * FROM staging.voice_campaign_settings WHERE campaign_id=:id',id=campaign_id).mappings().first()


def number(db,profile,identifier):
    row=query(db,'''SELECT *,verified_at>clock_timestamp()-interval '24 hours' AS fresh
        FROM staging.voice_numbers WHERE id=:id AND account_sid=:account''',id=identifier,account=profile.account_sid).mappings().first()
    if not row or not all(row[k] for k in ('voice_enabled','is_present','is_active','fresh')):
        raise HTTPException(409,'Le numéro émetteur doit être actif et vérifié dans votre compte Twilio.')
    return row


def regional_number(db,profile,campaign_id,destination):
    config=settings(db,campaign_id) if campaign_id else None
    if config is None:
        identifier=query(db,'SELECT id FROM staging.voice_numbers WHERE account_sid=:account AND number=:number',
                         account=profile.account_sid,number=profile.caller_number).scalar_one_or_none()
        if identifier is None:raise HTTPException(409,'Synchronisez les numéros Twilio avant d’appeler.')
        row=number(db,profile,identifier)
        return row['id'],row['number']
    try: country=phonenumbers.region_code_for_number(phonenumbers.parse(destination,None)) or ''
    except phonenumbers.NumberParseException: country=''
    rules=query(db,'''SELECT * FROM staging.voice_region_rules WHERE campaign_id=:id
        AND (country='' OR country=:country) AND (prefix='' OR starts_with(:destination,prefix))
        ORDER BY length(prefix) DESC,(country<>'') DESC,id LIMIT 1''',id=campaign_id,country=country,destination=destination).mappings().first()
    selected=rules['number_id'] if rules else config['default_number_id']
    if selected is None:
        raise HTTPException(409,'Choisissez le numéro émetteur de cette campagne.')
    row=number(db,profile,selected)
    return row['id'],row['number']


def campaign_allowed(db,user,campaign_id,now,automatic=False):
    campaign=campaigns.access(db,user,campaign_id)
    config=settings(db,campaign_id)
    if automatic and (not config or not config['enabled']):
        raise HTTPException(409,'Un administrateur doit choisir le numéro émetteur de cette campagne.')
    if config and config['hours'] and not within_hours(config['hours'],campaign['timezone'],now):
        raise HTTPException(409,'Cette campagne est hors de ses horaires d’appel.')
    return campaign


def attempt_limits(db,profile,destination,zone,now):
    first=query(db,'''SELECT attempt_timezone FROM staging.voice_intents WHERE account_sid=:account
        AND destination=:destination ORDER BY created_at,id LIMIT 1''',account=profile.account_sid,destination=destination).scalar_one_or_none()
    # The first recorded timezone is stable across campaign switches. Changing
    # a campaign timezone cannot grant another daily allowance for this contact.
    zone=first or zone
    local=now.astimezone(ZoneInfo(zone))
    start=datetime.combine(local.date(),time.min,ZoneInfo(zone))
    end=datetime.combine(local.date()+timedelta(days=1),time.min,ZoneInfo(zone))
    row=query(db,'''SELECT max(consumed_at) AS last_attempt,
        count(*) FILTER (WHERE consumed_at>=:start AND consumed_at<:end) AS today
        FROM staging.voice_intents WHERE account_sid=:account AND destination=:destination AND consumed_at IS NOT NULL''',
        account=profile.account_sid,destination=destination,start=start,end=end).mappings().one()
    if row['today']>=2:
        return zone,'daily_limit',end
    if row['last_attempt'] and now<row['last_attempt']+timedelta(hours=2):
        return zone,'cooldown',row['last_attempt']+timedelta(hours=2)
    return zone,None,None


def callback_for(db,contact_id):
    if not contact_id:return None
    return query(db,"SELECT * FROM staging.callbacks WHERE contact_id=:id AND status='scheduled' FOR UPDATE",id=contact_id).mappings().first()


def prepare_context(db,actor,profile,destination,campaign_id=None,automatic=None):
    now=query(db,'SELECT clock_timestamp()').scalar_one()
    contact=query(db,'SELECT * FROM staging.contacts WHERE phone=:phone',phone=destination).mappings().first()
    if campaign_id is None and contact:
        memberships=query(db,'''SELECT m.campaign_id FROM staging.campaign_contacts m JOIN staging.campaigns c ON c.id=m.campaign_id
            WHERE m.contact_id=:contact AND m.is_active AND c.is_active AND (:admin OR EXISTS(
                SELECT 1 FROM staging.campaign_agents ag WHERE ag.campaign_id=m.campaign_id AND ag.user_id=:actor AND ag.is_active))
            ORDER BY m.campaign_id LIMIT 2''',contact=contact['id'],admin=actor['role']=='admin',actor=actor['id']).scalars().all()
        if len(memberships)>1:raise HTTPException(400,'Choisissez la campagne d’origine de cet appel.')
        if memberships:campaign_id=memberships[0]
    campaign=campaign_allowed(db,actor,campaign_id,now,automatic is not None) if campaign_id else None
    # Every caller locks user -> dialer (if automatic) -> campaign -> canonical
    # contact -> callback -> account admission -> intent. Completion uses the
    # same order and never locks an intent before its CRM contact.
    if contact:
        contact=query(db,'SELECT * FROM staging.contacts WHERE id=:id FOR UPDATE',id=contact['id']).mappings().one()
        if contact['do_not_contact'] or contact['non_interested']:
            raise HTTPException(400,'Ce contact est marqué « Ne pas contacter » ou « Non intéressé ».')
    card=campaigns.contact_access(db,campaign_id,contact['id']) if campaign and contact else None
    if campaign and not card:raise HTTPException(400,'Ce numéro ne figure pas dans la campagne choisie.')
    callback=callback_for(db,contact['id'] if contact else None)
    if callback:
        if callback['owner_id']!=actor['id']:
            raise HTTPException(409,'Ce contact est réservé pour le rappel d’un autre agent.')
        if callback['due_at']>now:
            raise HTTPException(409,'Ce contact possède un rappel programmé plus tard.')
        if campaign_id!=callback['campaign_id']:
            raise HTTPException(400,'Appelez ce rappel depuis sa campagne d’origine.')
    selected_id,caller=regional_number(db,profile,campaign_id,destination)
    if caller==destination:raise HTTPException(400,'Le numéro à appeler doit être différent du numéro émetteur.')
    return dict(campaign_id=campaign_id,contact_id=contact['id'] if contact else None,
        callback_id=callback['id'] if callback else None,callback_version=callback['version'] if callback else None,
        membership_version=card['version'] if card else None,caller_number_id=selected_id,caller_number=caller,
        attempt_timezone=campaign['timezone'] if campaign else 'America/Toronto',
        dialer_generation=automatic['generation'] if automatic else None,
        dialer_browser_id=automatic['browser_id'] if automatic else None)


def authorize_context(db,actor,row,profile):
    now=query(db,'SELECT clock_timestamp()').scalar_one()
    if row['dialer_generation'] is not None:
        state=query(db,'SELECT * FROM staging.voice_dialer_sessions WHERE actor_id=:id FOR UPDATE',id=actor['id']).mappings().first()
        if (not state or state['mode']!='running' or state['generation']!=row['dialer_generation']
                or state['browser_id']!=row['dialer_browser_id'] or state['session_hash']!=row['session_hash']
                or state['lease_until']<=now or (row['callback_id'] is None and state['campaign_id']!=row['campaign_id'])):
            return False
    if row['campaign_id']:
        campaign_allowed(db,actor,row['campaign_id'],now,row['dialer_generation'] is not None)
    contact=query(db,'SELECT * FROM staging.contacts WHERE phone=:phone FOR UPDATE',phone=row['destination']).mappings().first()
    if row['contact_id'] and (not contact or contact['id']!=row['contact_id']):return False
    if contact:
        if contact['do_not_contact'] or contact['non_interested']:
            return False
        if row['campaign_id']:campaigns.contact_access(db,row['campaign_id'],contact['id'])
        callback=callback_for(db,contact['id'])
        if row['callback_id']:
            if (not callback or callback['id']!=row['callback_id'] or callback['version']!=row['callback_version']
                    or callback['owner_id']!=actor['id'] or callback['due_at']>now):return False
        elif callback:return False
    if row['caller_number_id']:
        selected=number(db,profile,row['caller_number_id'])
        if selected['number']!=row['caller_number']:return False
    elif row['caller_number']!=profile.caller_number:return False
    query(db,'SELECT pg_advisory_xact_lock(hashtextextended(:account,74192010))',account=profile.account_sid)
    return attempt_limits(db,profile,row['destination'],row['attempt_timezone'],now)[1] is None

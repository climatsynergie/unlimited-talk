"""GET-only owned-number discovery, with complete-page and lease validation."""
import json
import re
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit
import urllib.request
from uuid import uuid4

import phonenumbers
from app.identity.service import query
from app.telephony.reconciliation import configured_provider, NoRedirect
from app.telephony.twilio_voice import sid

MAX_BYTES = 1024 * 1024


class DirectoryError(ValueError):
    pass


def page_suffix(account, value=None):
    path = '/2010-04-01/Accounts/'+account+'/IncomingPhoneNumbers.json'
    if value is None:
        return '/IncomingPhoneNumbers.json?PageSize=100&Page=0'
    try:
        parsed = urlsplit(value)
        pairs = parse_qsl(parsed.query,strict_parsing=True,max_num_fields=3)
        values = dict(pairs)
        if (parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != path
                or len(pairs) != len(values) or set(values) - {'PageSize','Page','PageToken'}
                or values.get('PageSize') != '100' or not re.fullmatch(r'[0-9]{1,4}',values.get('Page',''))
                or not values.get('PageToken') or len(values['PageToken'])>1024
                or not values['PageToken'].isascii() or not values['PageToken'].isprintable()
                or any(c.isspace() for c in values['PageToken'])):
            raise ValueError
        return '/IncomingPhoneNumbers.json?'+urlencode({
            'PageSize':100,'Page':int(values['Page']),'PageToken':values['PageToken']})
    except (ValueError,TypeError):
        raise DirectoryError('provider_response_invalid') from None


class NumberReader:
    def __init__(self,profile,send=None):
        self.profile,self.transport,self.send = profile,configured_provider(profile),send

    def read(self):
        suffix = page_suffix(self.profile.account_sid)
        visited, numbers = set(), {}
        try:
            for _ in range(20):
                if suffix in visited: raise DirectoryError('provider_response_invalid')
                visited.add(suffix)
                request = urllib.request.Request(self.transport.base+suffix,method='GET',headers={
                    'Authorization':self.transport.authorization,'Accept':'application/json',
                    'Cache-Control':'no-cache','User-Agent':'Unlimited-Talks-caller-directory/1'})
                if self.send:
                    data = self.send(request)
                else:
                    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
                    with opener.open(request,timeout=8) as response:
                        if response.status != 200: raise DirectoryError('provider_unavailable')
                        raw=response.read(MAX_BYTES+1)
                    if len(raw)>MAX_BYTES: raise DirectoryError('provider_response_invalid')
                    data=json.loads(raw)
                if not isinstance(data,dict) or not isinstance(data.get('incoming_phone_numbers'),list) or 'next_page_uri' not in data:
                    raise DirectoryError('provider_response_invalid')
                if len(data['incoming_phone_numbers'])>100: raise DirectoryError('provider_response_invalid')
                for number in data['incoming_phone_numbers']:
                    if (not isinstance(number,dict) or number.get('account_sid')!=self.profile.account_sid
                            or not sid(number.get('sid'),'PN') or number['sid'] in numbers
                            or not isinstance(number.get('phone_number'),str)
                            or not re.fullmatch(r'\+[1-9][0-9]{8,14}',number['phone_number'])
                            or not isinstance(number.get('capabilities'),dict)
                            or type(number['capabilities'].get('voice')) is not bool
                            or not isinstance(number.get('friendly_name'),str)):
                        raise DirectoryError('provider_response_invalid')
                    try: country=phonenumbers.region_code_for_number(phonenumbers.parse(number['phone_number'],None)) or ''
                    except phonenumbers.NumberParseException: country=''
                    numbers[number['sid']] = dict(provider_sid=number['sid'],number=number['phone_number'],
                        name=number['friendly_name'][:200],country=country if len(country)==2 else '',
                        voice_enabled=number['capabilities']['voice'] and number.get('status','in-use')=='in-use')
                if data['next_page_uri'] in (None,''):
                    if len({n['number'] for n in numbers.values()}) != len(numbers):
                        raise DirectoryError('provider_response_invalid')
                    return list(numbers.values())
                suffix=page_suffix(self.profile.account_sid,data['next_page_uri'])
            raise DirectoryError('provider_response_invalid')
        except DirectoryError: raise
        except Exception: raise DirectoryError('provider_unavailable') from None


def synchronize_once(engine,profile,reader=None):
    if profile is None: return 'disabled'
    lease=uuid4()
    with engine.begin() as db:
        query(db,'''INSERT INTO staging.voice_directory_state(account_sid) VALUES (:account)
            ON CONFLICT DO NOTHING''',account=profile.account_sid)
        row=query(db,'''UPDATE staging.voice_directory_state SET lease_token=:lease,
            lease_until=clock_timestamp()+interval '5 minutes'
            WHERE account_sid=:account AND (lease_until IS NULL OR lease_until<=clock_timestamp())
              AND next_attempt_at<=clock_timestamp()
              AND (synchronized_at IS NULL OR synchronized_at<requested_at
                   OR synchronized_at<clock_timestamp()-interval '5 minutes') RETURNING account_sid''',
            account=profile.account_sid,lease=lease).first()
        if row is None:return 'idle'
    # No SQL connection or transaction survives the provider request.
    try:
        numbers=(reader or NumberReader(profile)).read()
        with engine.begin() as db:
            current=query(db,'''SELECT * FROM staging.voice_directory_state WHERE account_sid=:account
                AND lease_token=:lease FOR UPDATE''',account=profile.account_sid,lease=lease).mappings().first()
            if current is None:return 'stale'
            query(db,'UPDATE staging.voice_numbers SET is_present=false WHERE account_sid=:account',account=profile.account_sid)
            for number in numbers:
                query(db,'''INSERT INTO staging.voice_numbers(id,account_sid,provider_sid,number,name,country,voice_enabled,verified_at)
                    VALUES (:id,:account,:provider_sid,:number,:name,:country,:voice_enabled,clock_timestamp())
                    ON CONFLICT(account_sid,provider_sid) DO UPDATE SET number=excluded.number,name=excluded.name,
                        country=excluded.country,voice_enabled=excluded.voice_enabled,is_present=true,verified_at=excluded.verified_at''',
                    id=uuid4(),account=profile.account_sid,**number)
            query(db,'''UPDATE staging.voice_directory_state SET synchronized_at=clock_timestamp(),
                lease_token=NULL,lease_until=NULL,last_error_code=NULL,next_attempt_at=clock_timestamp()
                WHERE account_sid=:account AND lease_token=:lease''',account=profile.account_sid,lease=lease)
        return 'synchronized'
    except Exception as error:
        reason=error.args[0] if isinstance(error,DirectoryError) and error.args else 'provider_unavailable'
        with engine.begin() as db:
            query(db,'''UPDATE staging.voice_directory_state SET lease_token=NULL,lease_until=NULL,
                last_error_code=:reason,next_attempt_at=clock_timestamp()+interval '60 seconds'
                WHERE account_sid=:account AND lease_token=:lease''',account=profile.account_sid,lease=lease,
                reason=reason if reason in {'provider_unavailable','provider_response_invalid'} else 'provider_response_invalid')
        return 'retry_scheduled'

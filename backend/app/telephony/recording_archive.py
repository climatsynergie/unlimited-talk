"""Durable archive jobs: PG claim -> bounded media/storage I/O -> atomic result.

No DB connection is held over a provider/object-store request. Lease expiry only
retries an idempotent file copy; it never frees an uncertain telephone call.
"""
from dataclasses import dataclass
import io
import json
import logging
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request
from uuid import UUID, uuid4
import wave

from app.identity.service import query
from app.telephony import archive_storage, service
from app.telephony.reconciliation import configured_provider, NoRedirect
from app.telephony.twilio_voice import sid

logger = logging.getLogger(__name__)
REASONS = frozenset({'provider_unavailable','provider_authentication_failed','recording_not_available',
    'recording_identity_mismatch','recording_response_invalid','recording_too_large',
    'recording_format_invalid','archive_storage_unavailable','archive_job_invalid'})


class ArchiveError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class Job:
    recording_sid: str
    intent_id: UUID
    call_sid: str
    duration: int
    channels: int
    lease_token: UUID
    attempts: int

    def check(self):
        if (not sid(self.recording_sid,'RE') or not sid(self.call_sid,'CA')
                or not isinstance(self.intent_id,UUID) or not isinstance(self.lease_token,UUID)
                or type(self.duration) is not int or not 0 <= self.duration <= 600
                or self.channels != 2 or type(self.channels) is not int
                or type(self.attempts) is not int or not 1 <= self.attempts <= 1000000):
            raise ArchiveError('archive_job_invalid')


def inspect_wav(content, duration):
    if not isinstance(content,bytes) or not 44 <= len(content) <= archive_storage.MAX_BYTES:
        raise ArchiveError('recording_too_large')
    try:
        with wave.open(io.BytesIO(content),'rb') as audio:
            frames=audio.getnframes()
            if (audio.getnchannels()!=2 or audio.getsampwidth()!=2 or audio.getframerate()!=8000
                    or audio.getcomptype()!='NONE' or frames<=0 or frames>601*8000
                    or abs(frames/8000-duration)>1.05 or len(audio.readframes(frames))!=frames*4):
                raise ValueError
    except Exception:
        raise ArchiveError('recording_format_invalid') from None
    return 8000


class RecordingReader:
    def __init__(self, profile, send=None):
        self.profile,self.transport,self.send=profile,configured_provider(profile),send

    def _get(self, recording_sid, media=False):
        if not sid(recording_sid,'RE'):
            raise ArchiveError('archive_job_invalid')
        suffix='/Recordings/'+recording_sid+('.wav?RequestedChannels=2' if media else '.json')
        limit=archive_storage.MAX_BYTES if media else 65536
        request=urllib.request.Request(self.transport.base+suffix,method='GET',headers={
            'Authorization':self.transport.authorization,'Accept':'audio/wav' if media else 'application/json',
            'Cache-Control':'no-cache','User-Agent':'Unlimited-Talks-recording-archive/1'})
        try:
            if self.send:
                raw=self.send(request,limit)
            else:
                opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
                with opener.open(request,timeout=15) as response:
                    if response.status!=200:raise ArchiveError('recording_response_invalid')
                    raw=response.read(limit+1)
            if not isinstance(raw,bytes) or len(raw)>limit:
                raise ArchiveError('recording_too_large')
            return raw if media else json.loads(raw)
        except ArchiveError:raise
        except urllib.error.HTTPError as error:
            reason={401:'provider_authentication_failed',403:'provider_authentication_failed',
                    404:'recording_not_available'}.get(error.code,'provider_unavailable')
            raise ArchiveError(reason) from None
        except Exception:
            raise ArchiveError('provider_unavailable') from None

    def read(self,job):
        job.check()
        data=self._get(job.recording_sid)
        if (not isinstance(data,dict) or data.get('sid')!=job.recording_sid
                or data.get('account_sid')!=self.profile.account_sid or data.get('call_sid')!=job.call_sid
                or data.get('status')!='completed' or data.get('source')!='DialVerb'
                or data.get('channels')!=2 or type(data.get('channels')) is not int
                or data.get('duration')!=str(job.duration) or data.get('encryption_details') not in (None,{})):
            raise ArchiveError('recording_identity_mismatch')
        content=self._get(job.recording_sid,True)
        inspect_wav(content,job.duration)
        return content


def claim(engine,profile):
    with engine.begin() as db:
        # Also recover callbacks received while the compatibility application ran.
        query(db,'''INSERT INTO staging.voice_archive_jobs(recording_sid)
            SELECT r.sid FROM staging.voice_recordings r JOIN staging.voice_intents i ON i.id=r.intent_id
            WHERE r.state='pending_archive' AND i.profile_hash=:profile
            ON CONFLICT DO NOTHING''',profile=service.profile_hash(profile))
        row=query(db,'''SELECT r.sid AS recording_sid,r.intent_id,r.call_sid,r.duration,r.channels,j.attempts
            FROM staging.voice_archive_jobs j JOIN staging.voice_recordings r ON r.sid=j.recording_sid
            JOIN staging.voice_intents i ON i.id=r.intent_id
            WHERE r.state='pending_archive' AND j.archived_at IS NULL AND j.next_attempt_at<=clock_timestamp()
              AND (j.lease_until IS NULL OR j.lease_until<=clock_timestamp())
              AND i.profile_hash=:profile AND i.account_sid=:account AND i.parent_call_sid=r.call_sid
            ORDER BY j.next_attempt_at,j.recording_sid FOR UPDATE OF j SKIP LOCKED LIMIT 1''',
            profile=service.profile_hash(profile),account=profile.account_sid).mappings().first()
        if row is None:return None
        token=uuid4()
        query(db,'''UPDATE staging.voice_archive_jobs SET lease_token=:token,
            lease_until=clock_timestamp()+interval '300 seconds',attempts=attempts+1
            WHERE recording_sid=:sid''',token=token,sid=row['recording_sid'])
        return Job(**{**row,'attempts':row['attempts']+1,'lease_token':token})


def finish(engine,profile,job,content,key,checksum):
    job.check()
    rate=inspect_wav(content,job.duration)
    if key!=archive_storage.object_key(job.intent_id,job.recording_sid,checksum):
        raise ArchiveError('archive_job_invalid')
    import hashlib
    if hashlib.sha256(content).hexdigest()!=checksum:raise ArchiveError('archive_job_invalid')
    with engine.begin() as db:
        # Match callback lock order: intent -> recording -> job.
        intent=query(db,'SELECT * FROM staging.voice_intents WHERE id=:id FOR UPDATE',id=job.intent_id).mappings().first()
        service.bound(intent,profile)
        row=query(db,'SELECT * FROM staging.voice_recordings WHERE sid=:sid FOR UPDATE',sid=job.recording_sid).mappings().one()
        active=query(db,'SELECT * FROM staging.voice_archive_jobs WHERE recording_sid=:sid FOR UPDATE',sid=job.recording_sid).mappings().one()
        if row['state']=='archived':
            if row['object_key']!=key or row['checksum']!=checksum:raise ArchiveError('archive_job_invalid')
            return 'resolved_elsewhere'
        if (active['lease_token']!=job.lease_token or row['intent_id']!=job.intent_id or row['call_sid']!=job.call_sid
                or row['duration']!=job.duration or row['channels']!=job.channels):return 'stale'
        query(db,"UPDATE staging.voice_recordings SET state='archived',object_key=:key,checksum=:hash WHERE sid=:sid",
              key=key,hash=checksum,sid=job.recording_sid)
        query(db,'''UPDATE staging.voice_archive_jobs SET archived_at=clock_timestamp(),content_bytes=:size,
            sample_rate=:rate,lease_token=NULL,lease_until=NULL,last_error_code=NULL WHERE recording_sid=:sid''',
            size=len(content),rate=rate,sid=job.recording_sid)
        service.event(db,job.intent_id,'recording.archived',{'recording_sid':job.recording_sid,
            'checksum':checksum,'bytes':len(content)})
        return 'archived'


def fail(engine,job,reason):
    reason=reason if isinstance(reason,str) and reason in REASONS else 'provider_unavailable'
    delay=min(3600,15*2**min(job.attempts-1,8))
    with engine.begin() as db:
        row=query(db,'''UPDATE staging.voice_archive_jobs SET lease_token=NULL,lease_until=NULL,
            last_error_code=:reason,next_attempt_at=clock_timestamp()+make_interval(secs=>:delay)
            WHERE recording_sid=:sid AND lease_token=:token AND archived_at IS NULL RETURNING recording_sid''',
            reason=reason,delay=delay,sid=job.recording_sid,token=job.lease_token).first()
    return row is not None


def archive_once(engine,profile,reader=None,put=None):
    if profile is None:return 'disabled'
    job=claim(engine,profile)
    if job is None:return 'idle'
    try:
        content=(reader or RecordingReader(profile)).read(job)
        inspect_wav(content,job.duration)
        try:key,checksum=(put or archive_storage.put)(job.intent_id,job.recording_sid,content)
        except Exception:raise ArchiveError('archive_storage_unavailable') from None
        return finish(engine,profile,job,content,key,checksum)
    except Exception as error:
        reason=error.args[0] if isinstance(error,ArchiveError) and error.args else 'provider_unavailable'
        fail(engine,job,reason)
        return 'retry_scheduled'


def main():
    from app.database import make_engine
    from app.telephony.configuration import load_profile
    profile=load_profile()
    engine=make_engine() if profile is not None else None
    reader=RecordingReader(profile) if profile is not None else None
    try:
        while True:
            state='idle'
            try:
                state=archive_once(engine,profile,reader)
                Path('/tmp/voice-archive-heartbeat').touch()
                if state=='retry_scheduled':logger.warning('Archivage audio reporté ; reprise conservée en base.')
            except Exception:logger.warning('Archivage audio à reprendre.')
            time.sleep(0.25 if state in {'archived','retry_scheduled','stale','resolved_elsewhere'} else 5)
    finally:
        if engine is not None:engine.dispose()


if __name__=='__main__':main()

"""Private incoming audio copies: dual conversation or mono voicemail, never public URLs."""
import hashlib,os,tempfile,time
from pathlib import Path
from uuid import uuid4
from app.identity.service import query
from app.telephony import archive_storage
from app.telephony.incoming_schema import installed
from app.telephony.incoming_runtime import event
from app.telephony.recording_archive import Job,ArchiveError,RecordingReader,StoredMedia,REASONS,inspect_wav


class IncomingJob(Job):
    @property
    def recording_source(self):return 'RecordVerb' if self.channels==1 else 'DialVerb'

    def check(self):
        if type(self.channels) is not int or self.channels not in (1,2) or (self.channels==1 and self.duration>120):
            raise ArchiveError('archive_job_invalid')
        Job(self.recording_sid,self.intent_id,self.call_sid,self.duration,2,self.lease_token,self.attempts).check()


def claim(engine,profile):
    with engine.begin() as db:
        if not installed(db):return None
        row=query(db,'''SELECT r.sid AS recording_sid,r.call_id AS intent_id,r.call_sid,r.duration,r.channels,j.attempts
            FROM staging.inbound_archive_jobs j JOIN staging.inbound_recordings r ON r.sid=j.recording_sid
            JOIN staging.inbound_calls c ON c.id=r.call_id WHERE r.state='pending_archive' AND j.archived_at IS NULL
            AND j.next_attempt_at<=clock_timestamp() AND (j.lease_until IS NULL OR j.lease_until<=clock_timestamp())
            AND c.account_sid=:account AND c.parent_call_sid=r.call_sid
            ORDER BY j.next_attempt_at,j.recording_sid FOR UPDATE OF j SKIP LOCKED LIMIT 1''',account=profile.account_sid).mappings().first()
        if row is None:return None
        token=uuid4()
        query(db,'''UPDATE staging.inbound_archive_jobs SET lease_token=:token,lease_until=clock_timestamp()+interval '300 seconds',
            attempts=attempts+1 WHERE recording_sid=:sid''',token=token,sid=row['recording_sid'])
        return IncomingJob(**{**row,'lease_token':token,'attempts':row['attempts']+1})


def finish(engine,profile,job,media,key,checksum):
    job.check()
    if isinstance(media,StoredMedia):
        if media.checksum!=checksum or media.sample_rate!=8000 or not 44<=media.size<=archive_storage.MAX_BYTES:
            raise ArchiveError('archive_job_invalid')
        size=media.size
    else:
        inspect_wav(media,job.duration,job.channels);size=len(media)
        if hashlib.sha256(media).hexdigest()!=checksum:raise ArchiveError('archive_job_invalid')
    if key!=archive_storage.object_key(job.intent_id,job.recording_sid,checksum):raise ArchiveError('archive_job_invalid')
    with engine.begin() as db:
        call=query(db,'SELECT * FROM staging.inbound_calls WHERE id=:id FOR UPDATE',id=job.intent_id).mappings().one()
        row=query(db,'SELECT * FROM staging.inbound_recordings WHERE sid=:sid FOR UPDATE',sid=job.recording_sid).mappings().one()
        active=query(db,'SELECT * FROM staging.inbound_archive_jobs WHERE recording_sid=:sid FOR UPDATE',sid=job.recording_sid).mappings().one()
        if call['account_sid']!=profile.account_sid or call['parent_call_sid']!=job.call_sid:raise ArchiveError('archive_job_invalid')
        if row['state']=='archived':
            if row['object_key']!=key or row['checksum']!=checksum:raise ArchiveError('archive_job_invalid')
            return 'resolved_elsewhere'
        if (active['lease_token']!=job.lease_token or row['call_id']!=job.intent_id or row['call_sid']!=job.call_sid
                or row['duration']!=job.duration or row['channels']!=job.channels):return 'stale'
        query(db,"UPDATE staging.inbound_recordings SET state='archived',object_key=:key,checksum=:hash WHERE sid=:sid",key=key,hash=checksum,sid=job.recording_sid)
        query(db,'''UPDATE staging.inbound_archive_jobs SET archived_at=clock_timestamp(),content_bytes=:size,sample_rate=8000,
            lease_token=NULL,lease_until=NULL,last_error_code=NULL WHERE recording_sid=:sid''',size=size,sid=job.recording_sid)
        event(db,job.intent_id,'recording.archived',{'recording_sid':job.recording_sid,'checksum':checksum,'bytes':size})
    return 'archived'


def fail(engine,job,reason):
    reason=reason if isinstance(reason,str) and reason in REASONS else 'provider_unavailable'
    with engine.begin() as db:
        query(db,'''UPDATE staging.inbound_archive_jobs SET lease_token=NULL,lease_until=NULL,last_error_code=:reason,
            next_attempt_at=clock_timestamp()+make_interval(secs=>:delay)
            WHERE recording_sid=:sid AND lease_token=:token AND archived_at IS NULL''',sid=job.recording_sid,token=job.lease_token,
            reason=reason,delay=min(3600,15*2**min(job.attempts-1,8)))


def archive_once(engine,profile,reader=None,put=None):
    if profile is None:return 'disabled'
    job=claim(engine,profile)
    if job is None:return 'idle'
    try:
        reader=reader or RecordingReader(profile)
        touched=time.monotonic()
        def progress():
            nonlocal touched
            now=time.monotonic()
            if now-touched<30:return
            with engine.begin() as db:
                alive=query(db,'''UPDATE staging.inbound_archive_jobs SET lease_until=clock_timestamp()+interval '300 seconds'
                    WHERE recording_sid=:sid AND lease_token=:token AND archived_at IS NULL RETURNING recording_sid''',sid=job.recording_sid,token=job.lease_token).first()
                if alive is None:raise ArchiveError('archive_job_invalid')
            Path('/tmp/voice-archive-heartbeat').touch();touched=now
        if put is None and hasattr(reader,'read_to_file'):
            with tempfile.TemporaryFile(dir=os.environ.get('RECORDING_SCRATCH_DIR','/tmp')) as source:
                rate=reader.read_to_file(job,source,progress)
                try:key,checksum,size=archive_storage.put_file(job.intent_id,job.recording_sid,source,progress)
                except ArchiveError:raise
                except Exception:raise ArchiveError('archive_storage_unavailable') from None
                return finish(engine,profile,job,StoredMedia(size,checksum,rate),key,checksum)
        content=reader.read(job)
        inspect_wav(content,job.duration,job.channels)
        try:key,checksum=(put or archive_storage.put)(job.intent_id,job.recording_sid,content)
        except Exception:raise ArchiveError('archive_storage_unavailable') from None
        return finish(engine,profile,job,content,key,checksum)
    except Exception as error:
        reason=error.args[0] if isinstance(error,ArchiveError) and error.args else 'provider_unavailable'
        fail(engine,job,reason)
        return 'retry_scheduled'

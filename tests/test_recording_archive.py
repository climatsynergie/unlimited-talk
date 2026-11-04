import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch,MagicMock
from uuid import uuid4
import wave
from fastapi import HTTPException
from app.telephony import archive_storage
from app.telephony.recording_archive import ArchiveError,Job,RecordingReader,inspect_wav,inspect_wav_file,archive_once
from app.telephony.recording_routes import byte_range
from app.telephony.twilio_voice import ControlledVoiceProfile


def wav(seconds=1,channels=2,rate=8000):
    data=io.BytesIO()
    with wave.open(data,'wb') as audio:
        audio.setnchannels(channels);audio.setsampwidth(2);audio.setframerate(rate)
        audio.writeframes(b'\x00\x00'*(rate*seconds*channels))
    return data.getvalue()


class RecordingArchiveTests(unittest.TestCase):
    def setUp(self):
        self.profile=ControlledVoiceProfile('AC'+'a'*32,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
            'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100','+14165550101')
        self.job=Job('RE'+'1'*32,uuid4(),'CA'+'2'*32,1,2,uuid4(),1)
        self.content=wav()
        self.metadata=dict(sid=self.job.recording_sid,account_sid=self.profile.account_sid,
            call_sid=self.job.call_sid,status='completed',source='DialVerb',channels=2,duration='1',
            encryption_details=None,media_url='http://169.254.169.254/never-follow')
        self.requests=[]

    def reader(self,metadata=None,content=None):
        def send(request,limit):
            self.requests.append(request)
            self.assertEqual(request.method,'GET')
            return (content if content is not None else self.content) if '.wav?' in request.full_url else json.dumps(metadata or self.metadata).encode()
        with patch.dict(os.environ,{'DB_DEPLOYMENT':'local'}):return RecordingReader(self.profile,send)

    def test_only_expected_recording_is_downloaded_from_fixed_provider_paths(self):
        self.assertEqual(self.reader().read(self.job),self.content)
        self.assertEqual([r.full_url for r in self.requests],[
            'https://api.twilio.com/2010-04-01/Accounts/'+self.profile.account_sid+'/Recordings/'+self.job.recording_sid+'.json',
            'https://api.twilio.com/2010-04-01/Accounts/'+self.profile.account_sid+'/Recordings/'+self.job.recording_sid+'.wav?RequestedChannels=2'])

    def test_foreign_account_call_source_or_channel_prevents_media_read(self):
        for change in [dict(account_sid='AC'+'9'*32),dict(call_sid='CA'+'9'*32),dict(source='RecordVerb'),
                       dict(channels=1),dict(channels=True),dict(status='processing'),dict(duration='99')]:
            self.requests.clear()
            with self.assertRaises(ArchiveError):self.reader(self.metadata|change).read(self.job)
            self.assertEqual(len(self.requests),1)

    def test_invalid_or_truncated_media_is_never_accepted(self):
        for content in [b'not audio',self.content[:-10],wav(channels=1),wav(rate=16000),wav(seconds=3)]:
            with self.assertRaises(ArchiveError):inspect_wav(content,1)
        self.assertEqual(inspect_wav(self.content,1),8000)

    def test_private_content_addressed_upload_is_read_back_and_verified(self):
        objects={};s3=MagicMock()
        def put(**kwargs):
            self.assertEqual(kwargs['ACL'],'private');self.assertEqual(kwargs['ContentType'],'audio/wav')
            objects[kwargs['Key']]=kwargs['Body']
        s3.put_object.side_effect=put
        s3.get_object.side_effect=lambda **kw:{'Body':io.BytesIO(objects[kw['Key']])}
        with patch.object(archive_storage,'client',return_value=(s3,'private-bucket')):
            key,checksum=archive_storage.put(self.job.intent_id,self.job.recording_sid,self.content)
            self.assertEqual(checksum,hashlib.sha256(self.content).hexdigest())
            self.assertEqual(archive_storage.read(key,checksum,len(self.content)),self.content)
            self.assertEqual(archive_storage.put(self.job.intent_id,self.job.recording_sid,self.content),(key,checksum))
            objects[key]=b'X'+self.content[1:]
            with self.assertRaises(ValueError):archive_storage.read(key,checksum,len(self.content))
        self.assertEqual(len(objects),1)

    def test_object_paths_cannot_escape_the_recording_namespace(self):
        checksum=hashlib.sha256(self.content).hexdigest()
        for key in ['imports/file.csv','../recordings/file.wav','https://untrusted.invalid/file',
                    f'recordings/{"-"*36}/{self.job.recording_sid}/{checksum}.wav']:
            with patch.object(archive_storage,'client') as s3:
                with self.assertRaises((ValueError,TypeError)):archive_storage.read(key,checksum,len(self.content))
                s3.assert_not_called()

    def test_disabled_worker_never_opens_database_provider_or_storage(self):
        engine=MagicMock();provider=MagicMock();put=MagicMock()
        self.assertEqual(archive_once(engine,None,provider,put),'disabled')
        engine.begin.assert_not_called();provider.read.assert_not_called();put.assert_not_called()

    def test_audio_ranges_support_browser_seek_without_multi_range_requests(self):
        for header,expected in [(None,(0,99,200)),('bytes=0-',(0,99,206)),('bytes=5-9',(5,9,206)),
            ('bytes=-10',(90,99,206)),('bytes=-1000',(0,99,206)),('bytes=90-1000',(90,99,206))]:
            self.assertEqual(byte_range(header,100),expected)
        for header in ['bytes=100-','bytes=5-3','bytes=-0','bytes=0-1,4-5','items=0-2','bytes=-']:
            with self.assertRaises(HTTPException) as e:byte_range(header,100)
            self.assertEqual(e.exception.status_code,416)

    def test_streamed_long_media_is_validated_uploaded_private_and_seekable(self):
        content=wav(seconds=900)
        class BoundedBody(io.BytesIO):
            def read(inner,size=-1):
                self.assertGreater(size,0)
                self.assertLessEqual(size,65536)
                return super().read(size)
        objects={};s3=MagicMock()
        def upload(source,bucket,key,**kwargs):
            self.assertEqual(kwargs['ExtraArgs']['ACL'],'private')
            self.assertFalse(kwargs['Config'].use_threads)
            objects[key]=(source.read(),kwargs['ExtraArgs']['Metadata'])
            kwargs['Callback'](len(objects[key][0]))
        def get(**kw):
            data=objects[kw['Key']][0]
            if 'Range' in kw:
                first,last=map(int,kw['Range'][6:].split('-'))
                return dict(Body=BoundedBody(data[first:last+1]),ContentLength=last-first+1,
                            ContentRange=f'bytes {first}-{last}/{len(data)}')
            return dict(Body=BoundedBody(data),ContentLength=len(data))
        s3.upload_fileobj.side_effect=upload
        s3.get_object.side_effect=get
        s3.head_object.side_effect=lambda **kw:dict(ContentLength=len(objects[kw['Key']][0]),Metadata=objects[kw['Key']][1])
        self.assertEqual(inspect_wav_file(io.BytesIO(content),900),8000)
        with self.assertRaises(ArchiveError):inspect_wav_file(io.BytesIO(content[:-4]),900)
        progress=MagicMock()
        with patch.object(archive_storage,'client',return_value=(s3,'private-bucket')):
            key,checksum,size=archive_storage.put_file(self.job.intent_id,self.job.recording_sid,io.BytesIO(content),progress)
            self.assertEqual(size,len(content));self.assertGreater(size,24*1024*1024)
            self.assertEqual(checksum,hashlib.sha256(content).hexdigest())
            chunks,close=archive_storage.open_range(key,checksum,size,size-100,size-1)
            self.assertEqual(b''.join(chunks),content[-100:]);close()
            chunks,close=archive_storage.open_range(key,checksum,size,0,size-1)
            self.assertEqual(hashlib.sha256(b''.join(chunks)).hexdigest(),checksum);close()
            objects[key]=(b'X'+content[1:],objects[key][1])
            with self.assertRaises(ValueError):archive_storage.verify(key,checksum,size)
            with self.assertRaises(ValueError):archive_storage.read(key,checksum,size)
        self.assertGreater(progress.call_count,400)

    def test_streamed_provider_reader_validates_identity_and_media(self):
        source=io.BytesIO()
        self.assertEqual(self.reader().read_to_file(self.job,source),8000)
        self.assertEqual(source.read(),self.content)
        source=io.BytesIO()
        with self.assertRaises(ArchiveError):
            self.reader(self.metadata|{'call_sid':'CA'+'9'*32}).read_to_file(self.job,source)
        self.assertEqual(source.getvalue(),b'')

    def test_provider_media_download_reads_bounded_chunks_and_rejects_oversize(self):
        class Response(io.BytesIO):
            status=200
            headers={}
        class Media(Response):
            def read(inner,size=-1):
                self.assertGreater(size,0)
                self.assertLessEqual(size,65536)
                return super().read(size)
        opener=MagicMock()
        opener.open.side_effect=[Response(json.dumps(self.metadata).encode()),Media(self.content)]
        progress=MagicMock();source=io.BytesIO()
        with patch('app.telephony.recording_archive.urllib.request.build_opener',return_value=opener):
            self.assertEqual(RecordingReader(self.profile).read_to_file(self.job,source,progress),8000)
        self.assertEqual(source.read(),self.content);self.assertGreater(progress.call_count,0)
        media=Media(b'');media.headers={'Content-Length':str(archive_storage.MAX_BYTES+1)}
        opener.open.side_effect=[Response(json.dumps(self.metadata).encode()),media]
        with patch('app.telephony.recording_archive.urllib.request.build_opener',return_value=opener):
            with self.assertRaisesRegex(ArchiveError,'recording_too_large'):
                RecordingReader(self.profile).read_to_file(self.job,io.BytesIO())

    def test_range_metadata_mismatch_closes_transport_without_returning_audio(self):
        checksum=hashlib.sha256(self.content).hexdigest()
        key=archive_storage.object_key(self.job.intent_id,self.job.recording_sid,checksum)
        s3=MagicMock();body=MagicMock()
        s3.head_object.return_value=dict(ContentLength=len(self.content),Metadata={'sha256':checksum})
        s3.get_object.return_value=dict(Body=body,ContentLength=5,ContentRange='bytes 0-4/999')
        with patch.object(archive_storage,'client',return_value=(s3,'bucket')):
            with self.assertRaises(ValueError):archive_storage.open_range(key,checksum,len(self.content),0,4)
        body.close.assert_called_once();body.read.assert_not_called()

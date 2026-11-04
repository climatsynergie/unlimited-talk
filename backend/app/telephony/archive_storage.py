"""Private immutable recording objects; no provider URLs or public links."""
import hashlib
import re
from uuid import UUID
from boto3.s3.transfer import TransferConfig
from app.contacts.storage import client
from app.telephony.media_limits import MAX_RECORDING_BYTES, LEGACY_BUFFER_BYTES, STREAM_CHUNK_BYTES

MAX_BYTES = MAX_RECORDING_BYTES


def object_key(intent_id, recording_sid, checksum):
    if (not isinstance(intent_id, UUID) or not isinstance(recording_sid, str)
            or not re.fullmatch('RE[0-9a-fA-F]{32}', recording_sid)
            or not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum)):
        raise ValueError('Identité de fichier invalide.')
    return f'recordings/{intent_id}/{recording_sid}/{checksum}.wav'


def read(key, checksum, size):
    if size > LEGACY_BUFFER_BYTES:
        raise ValueError('Cette archive doit être lue en flux.')
    if (not isinstance(checksum,str) or not re.fullmatch('[0-9a-f]{64}',checksum)
            or not isinstance(key, str) or not re.fullmatch(
            r'recordings/[0-9a-f-]{36}/RE[0-9a-fA-F]{32}/[0-9a-f]{64}\.wav', key)
            or key.rsplit('/', 1)[-1] != checksum+'.wav'
            or type(size) is not int or not 44 <= size <= MAX_BYTES):
        raise ValueError('Archive invalide.')
    parts=key.split('/')
    if key!=object_key(UUID(parts[1]),parts[2],checksum):
        raise ValueError('Identité de fichier invalide.')
    transport, bucket = client(multipart=True)
    response = transport.get_object(Bucket=bucket, Key=key)
    stream = response['Body']
    try:
        content = stream.read(size+1)
    finally:
        stream.close()
    if len(content) != size or hashlib.sha256(content).hexdigest() != checksum:
        raise ValueError('Intégrité de l’archive non vérifiée.')
    return content


def put(intent_id, recording_sid, content):
    if not isinstance(content, bytes) or not 44 <= len(content) <= LEGACY_BUFFER_BYTES:
        raise ValueError('Fichier audio trop volumineux ou invalide.')
    checksum = hashlib.sha256(content).hexdigest()
    key = object_key(intent_id, recording_sid, checksum)
    transport, bucket = client(multipart=True)
    # Repeating the same upload writes the same bytes at a content-addressed key.
    # A crash before the PG commit cannot produce a second business recording.
    transport.put_object(Bucket=bucket, Key=key, Body=content, ACL='private',
                         ContentType='audio/wav', Metadata={'sha256':checksum})
    if read(key, checksum, len(content)) != content:
        raise ValueError('Copie privée non vérifiée.')
    return key, checksum


def validate_reference(key, checksum, size):
    if (not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum)
            or not isinstance(key, str) or not re.fullmatch(
                r'recordings/[0-9a-f-]{36}/RE[0-9a-fA-F]{32}/[a-f0-9]{64}\.wav', key)
            or type(size) is not int or not 44 <= size <= MAX_BYTES):
        raise ValueError('Archive invalide.')
    parts = key.split('/')
    if key != object_key(UUID(parts[1]), parts[2], checksum):
        raise ValueError('Identité de fichier invalide.')


def verify(key, checksum, size, progress=lambda: None):
    """Verify the complete immutable object with bounded memory."""
    validate_reference(key, checksum, size)
    transport, bucket = client(multipart=True)
    response = transport.get_object(Bucket=bucket, Key=key)
    body = response['Body']
    total = 0
    digest = hashlib.sha256()
    try:
        while chunk := body.read(STREAM_CHUNK_BYTES):
            total += len(chunk)
            if total > size:
                raise ValueError('Taille de l’archive invalide.')
            digest.update(chunk)
            progress()
    finally:
        body.close()
    if total != size or digest.hexdigest() != checksum:
        raise ValueError('Intégrité de l’archive non vérifiée.')


def put_file(intent_id, recording_sid, source, progress=lambda: None):
    """Content-addressed multipart upload from a private, seekable spool file."""
    source.seek(0, 2)
    size = source.tell()
    if not 44 <= size <= MAX_BYTES:
        raise ValueError('Fichier audio trop volumineux ou invalide.')
    source.seek(0)
    digest = hashlib.sha256()
    while chunk := source.read(STREAM_CHUNK_BYTES):
        digest.update(chunk)
        progress()
    checksum = digest.hexdigest()
    key = object_key(intent_id, recording_sid, checksum)
    source.seek(0)
    transport, bucket = client(multipart=True)
    transport.upload_fileobj(source, bucket, key,
        ExtraArgs={'ACL': 'private', 'ContentType': 'audio/wav', 'Metadata': {'sha256': checksum}},
        Config=TransferConfig(multipart_threshold=8*1024*1024, multipart_chunksize=8*1024*1024,
                              max_concurrency=1, use_threads=False),
        Callback=lambda count: progress())
    verify(key, checksum, size, progress)
    return key, checksum, size


def open_range(key, checksum, size, start, end):
    """Open an authorized range of a previously verified immutable recording."""
    validate_reference(key, checksum, size)
    if type(start) is not int or type(end) is not int or not 0 <= start <= end < size:
        raise ValueError('Plage audio invalide.')
    transport, bucket = client(multipart=True)
    head = transport.head_object(Bucket=bucket, Key=key)
    if head.get('ContentLength') != size or head.get('Metadata', {}).get('sha256') != checksum:
        raise ValueError('Métadonnées de l’archive non vérifiées.')
    whole = start == 0 and end == size-1
    options = {} if whole else {'Range': f'bytes={start}-{end}'}
    response = transport.get_object(Bucket=bucket, Key=key, **options)
    body = response['Body']
    length = end-start+1
    if (response.get('ContentLength') != length or
            (not whole and response.get('ContentRange') != f'bytes {start}-{end}/{size}')):
        body.close()
        raise ValueError('Réponse audio invalide.')

    def chunks():
        total = 0
        digest = hashlib.sha256() if whole else None
        try:
            while chunk := body.read(min(STREAM_CHUNK_BYTES, length-total+1)):
                total += len(chunk)
                if total > length:
                    raise ValueError('Taille de l’archive invalide.')
                if digest is not None:
                    digest.update(chunk)
                yield chunk
            if total != length or (digest is not None and digest.hexdigest() != checksum):
                raise ValueError('Intégrité de l’archive non vérifiée.')
        finally:
            body.close()
    return chunks(), body.close

"""Private immutable recording objects; no provider URLs or public links."""
import hashlib
import re
from uuid import UUID
from app.contacts.storage import client

MAX_BYTES = 24 * 1024 * 1024


def object_key(intent_id, recording_sid, checksum):
    if (not isinstance(intent_id, UUID) or not isinstance(recording_sid, str)
            or not re.fullmatch('RE[0-9a-fA-F]{32}', recording_sid)
            or not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum)):
        raise ValueError('Identité de fichier invalide.')
    return f'recordings/{intent_id}/{recording_sid}/{checksum}.wav'


def read(key, checksum, size):
    if (not isinstance(checksum,str) or not re.fullmatch('[0-9a-f]{64}',checksum)
            or not isinstance(key, str) or not re.fullmatch(
            r'recordings/[0-9a-f-]{36}/RE[0-9a-fA-F]{32}/[0-9a-f]{64}\.wav', key)
            or key.rsplit('/', 1)[-1] != checksum+'.wav'
            or type(size) is not int or not 44 <= size <= MAX_BYTES):
        raise ValueError('Archive invalide.')
    parts=key.split('/')
    if key!=object_key(UUID(parts[1]),parts[2],checksum):
        raise ValueError('Identité de fichier invalide.')
    transport, bucket = client()
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
    if not isinstance(content, bytes) or not 44 <= len(content) <= MAX_BYTES:
        raise ValueError('Fichier audio trop volumineux ou invalide.')
    checksum = hashlib.sha256(content).hexdigest()
    key = object_key(intent_id, recording_sid, checksum)
    transport, bucket = client()
    # Repeating the same upload writes the same bytes at a content-addressed key.
    # A crash before the PG commit cannot produce a second business recording.
    transport.put_object(Bucket=bucket, Key=key, Body=content, ACL='private',
                         ContentType='audio/wav', Metadata={'sha256':checksum})
    if read(key, checksum, len(content)) != content:
        raise ValueError('Copie privée non vérifiée.')
    return key, checksum

"""Private S3 transport. Credentials and endpoints come only from file secrets."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from botocore.config import Config

MAX_BYTES = 10 * 1024 * 1024


def client():
    config = json.loads(Path(os.environ['SPACES_CONFIG_FILE']).read_text())
    endpoint = urlsplit(config['endpoint'])
    local = os.environ.get('DB_DEPLOYMENT', 'local') == 'local'
    if local:
        if config['endpoint'] != 'http://objectstore:9000':
            raise RuntimeError('Unexpected disposable object store')
    elif (endpoint.scheme != 'https' or endpoint.hostname != config['region'] + '.digitaloceanspaces.com'
          or endpoint.path or endpoint.query or endpoint.username):
        raise RuntimeError('Invalid verified object storage endpoint')
    transport = boto3.client('s3', endpoint_url=config['endpoint'], region_name=config['region'],
        aws_access_key_id=config['access_key_id'], aws_secret_access_key=config['secret_access_key'],
        config=Config(connect_timeout=5, read_timeout=15, retries={'max_attempts': 1},
                      s3={'addressing_style': 'path'}))
    return transport, config['bucket']


def put_source(key, source):
    transport, bucket = client()
    transport.put_object(Bucket=bucket, Key=key, Body=source, ACL='private', ContentType='text/csv')
    return hashlib.sha256(source).hexdigest()


def read_source(key, expected):
    transport, bucket = client()
    response = transport.get_object(Bucket=bucket, Key=key)
    stream = response['Body']
    try:
        source = stream.read(MAX_BYTES + 1)
    finally:
        stream.close()
    if len(source) > MAX_BYTES or hashlib.sha256(source).hexdigest() != expected:
        raise ValueError('Le fichier source a changé. Créez un nouvel import.')
    return source

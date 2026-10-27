"""Run real-browser tests through ephemeral local HTTPS; no managed data allowed."""
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit

root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
extra=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
if not any(x in {'-f','--file'} or x.startswith('--file=') for x in extra): compose+=['-f',str(root/'compose.yaml')]
compose+=extra
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
upstream=urlsplit(os.environ.get('FOUNDATION_TEST_URL','http://127.0.0.1:8110'))
assert upstream.hostname=='127.0.0.1'


class Proxy(BaseHTTPRequestHandler):
    def log_message(self,*args): pass  # No URLs, cookies, request bodies or secrets in logs.
    def forward(self):
        client=http.client.HTTPConnection(upstream.hostname,upstream.port,timeout=20)
        try:
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            headers={k:v for k,v in self.headers.items() if k.lower() not in {'connection','transfer-encoding'}}
            client.request(self.command,self.path,body=body,headers=headers)
            response=client.getresponse();data=response.read()
            self.send_response(response.status)
            for key,value in response.getheaders():
                if key.lower() not in {'connection','transfer-encoding','content-length','server','date'}: self.send_header(key,value)
            self.send_header('Content-Length',str(len(data)));self.end_headers()
            if self.command!='HEAD': self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError,ssl.SSLEOFError):
            pass  # Browser navigation may cancel an in-flight response.
        finally: client.close()
    do_GET=forward
    do_POST=forward
    do_PUT=forward
    do_PATCH=forward
    do_DELETE=forward
    do_HEAD=forward


with tempfile.TemporaryDirectory(prefix='ut-browser-https-') as tmp:
    folder=Path(tmp);cert=folder/'certificate.pem';key=folder/'private.key';override=folder/'browser.yaml'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    override.write_text('services:\n  api:\n    environment:\n      APP_ORIGIN: https://localhost:18443\n')
    server=None
    try:
        subprocess.run([*compose,'-f',str(override),'up','-d','--no-deps','--no-build','--wait','--wait-timeout','120','api'],check=True)
        # The gateway caches Docker DNS briefly across API replacement.
        for attempt in range(15):
            try:
                with urllib.request.urlopen(upstream.geturl()+'/health/ready',timeout=5) as response:
                    ready=json.load(response)
                if ready.get('revision')==os.environ.get('GITHUB_SHA','development'):
                    break
            except (urllib.error.URLError,TimeoutError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Browser gateway did not reach the new API')
        server=ThreadingHTTPServer(('127.0.0.1',18443),Proxy)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
        server.socket=context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        env={**os.environ,'UI_TEST_URL':'https://localhost:18443'}
        subprocess.run(['npm','run','test:browser',*(['--',*sys.argv[1:]] if len(sys.argv)>1 else [])],cwd=root/'frontend',env=env,check=True)
    finally:
        if server: server.shutdown();server.server_close()
        subprocess.run([*compose,'up','-d','--no-deps','--no-build','--wait','--wait-timeout','120','api'],check=True)

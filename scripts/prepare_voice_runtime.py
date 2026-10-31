"""Root-owned runtime preparation: private mounts and a GET-only provider gate.

No call activation, database write, public webhook exception or Twilio Rule is
performed by prepare/read-gateway. Public hooks require a deployed safe-mode API.
Secrets never appear on command lines or in reports.
"""
import argparse
import base64
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import urllib.request

import twilio_voice_preflight as voice
import twilio_voice_signing as signing
from staging_twilio_preflight import PreflightError, read_private, write_private

ROOT = voice.PLAN.parent
CADDY = Path('/etc/caddy/Caddyfile')
FRAGMENT = Path('/etc/caddy/unlimited-talk-voice-read.caddy')
RUNTIME = ROOT / 'voice-runtime.json'
TOKEN = ROOT / 'voice-read-auth'
GATEWAY = ROOT / 'voice-read-gateway.json'


def render_gateway(config, token):
    if (not re.fullmatch('AC[0-9a-fA-F]{32}', config['account_sid'])
            or not re.fullmatch('SK[0-9a-fA-F]{32}', config['api_key_sid'])
            or not re.fullmatch('[0-9a-f]{64}', token)):
        raise PreflightError('Paramètres de passerelle invalides.')
    base = '/2010-04-01/Accounts/' + config['account_sid']
    pattern = '^' + base + r'/Calls/CA[0-9a-fA-F]{32}\.json$|^' + base + r'/Calls\.json\?ParentCallSid=CA[0-9a-fA-F]{32}&PageSize=2$'
    expression = '{http.request.uri}.matches(' + json.dumps(pattern) + ')'
    auth = base64.b64encode((config['api_key_sid'] + ':' + config['api_key_secret']).encode()).decode()
    return f'''http://172.30.8.1:8112 {{
    bind 172.30.8.1
    @voice_read {{
        method GET
        header Authorization "Bearer {token}"
        expression `{expression}`
    }}
    header Cache-Control no-store
    route {{
        reverse_proxy @voice_read https://api.twilio.com {{
            method GET
            header_up Host api.twilio.com
            header_up Authorization "Basic {auth}"
            header_up -Cookie
            header_up -Proxy-Authorization
            header_up -X-HTTP-Method-Override
            header_up -X-Method-Override
            header_up -X-HTTP-Method
            transport http {{
                dial_timeout 3s
                response_header_timeout 5s
                tls_server_name api.twilio.com
            }}
        }}
        respond 403
    }}
}}
'''


def render_hooks(original):
    if '@unlimited_talk_voice' in original:
        return original
    old = ('\t\timport /etc/caddy/staging-access.caddy\n'
           '\t\treverse_proxy 127.0.0.1:8110 {\n\t\t\theader_up -Authorization\n\t\t}\n')
    if original.count(old) != 1:
        raise PreflightError('Structure du proxy inattendue ; aucun remplacement.')
    uuid = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    new = f'''\t\t@unlimited_talk_voice {{
\t\t\tmethod POST
\t\t\tpath_regexp voice ^/api/telephony/twilio/(probe|voice|parent-status|(status|finish|recording)/{uuid})$
\t\t}}
\t\thandle @unlimited_talk_voice {{
\t\t\treverse_proxy 127.0.0.1:8110 {{
\t\t\t\theader_up -Authorization
\t\t\t}}
\t\t}}
\t\thandle {{
\t\t\timport /etc/caddy/staging-access.caddy
\t\t\treverse_proxy 127.0.0.1:8110 {{
\t\t\t\theader_up -Authorization
\t\t\t}}
\t\t}}
'''
    return original.replace(old, new)


def export_private(path, data):
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 10001
                or stat.S_IMODE(info.st_mode) != 0o440 or info.st_nlink != 1 or path.read_bytes() != data):
            raise PreflightError('Un fichier runtime différent ou non privé existe déjà.')
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data);out.flush();os.fchown(out.fileno(), 0, 10001);os.fchmod(out.fileno(), 0o440);os.fsync(out.fileno())
    sync_directory(path.parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def replace_caddy(candidate):
    info = CADDY.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_nlink != 1:
        raise PreflightError('Configuration du proxy non protégée.')
    original = CADDY.read_bytes()
    caddy_gid = grp.getgrnam('caddy').gr_gid
    staging = CADDY.with_name('voice-candidate.caddy')
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(candidate.encode());out.flush();os.fchown(out.fileno(), 0, caddy_gid);os.fchmod(out.fileno(), 0o640);os.fsync(out.fileno())
        result = subprocess.run(['caddy','validate','--config',str(staging),'--adapter','caddyfile'],
            env={**os.environ, 'STAGING_DOMAIN':'staging.unlimitedtalkapp.com'},capture_output=True,timeout=30)
        if result.returncode:
            raise PreflightError('La validation du proxy a échoué ; configuration active conservée.')
        # Keep a private exact backup; no config or command output reaches logs.
        backup = ROOT / ('caddy-before-' + hashlib.sha256(original).hexdigest() + '.txt')
        if not backup.exists():
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd,'wb') as out:out.write(original);out.flush();os.fsync(out.fileno())
        if CADDY.read_bytes() != original:
            raise PreflightError('Le proxy a changé pendant la préparation ; aucun remplacement.')
        os.replace(staging, CADDY);sync_directory(CADDY.parent)
        result = subprocess.run(['systemctl','reload','caddy'],capture_output=True,timeout=30)
        if result.returncode:
            # Restore the already validated previous file without outputting it.
            fd = os.open(staging,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o640)
            with os.fdopen(fd,'wb') as out:
                out.write(original);out.flush();os.fchown(out.fileno(),0,caddy_gid);os.fsync(out.fileno())
            os.replace(staging,CADDY);sync_directory(CADDY.parent)
            subprocess.run(['systemctl','reload','caddy'],capture_output=True,timeout=30,check=True)
            raise PreflightError('Rechargement refusé ; proxy précédent restauré.')
    finally:
        staging.unlink(missing_ok=True)


def prepare(config):
    signing.run('check', config)
    profile = read_private(signing.PROFILE)
    from twilio_voice_application import JOURNAL as APPLICATION
    expected = signing.assemble(config, read_private(signing.JOURNAL), read_private(signing.KEY), read_private(APPLICATION))
    if profile != expected:
        raise PreflightError('Profil Voice différent des ressources vérifiées.')
    if not GATEWAY.exists():write_private({'version':1,'token':secrets.token_hex(32)},GATEWAY)
    gateway = read_private(GATEWAY)
    if set(gateway) != {'version','token'} or gateway['version'] != 1 or not re.fullmatch('[0-9a-f]{64}',gateway['token']):
        raise PreflightError('Clé de passerelle invalide.')
    export_private(RUNTIME,(json.dumps(profile)+'\n').encode())
    export_private(TOKEN,(gateway['token']+'\n').encode())
    rendered = render_gateway(config,gateway['token']).encode()
    caddy_gid = grp.getgrnam('caddy').gr_gid
    if FRAGMENT.exists() or FRAGMENT.is_symlink():
        info=FRAGMENT.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_gid!=caddy_gid
                or stat.S_IMODE(info.st_mode)!=0o640 or info.st_nlink!=1 or FRAGMENT.read_bytes()!=rendered):
            raise PreflightError('Un fragment de passerelle différent existe déjà.')
    else:
        fd=os.open(FRAGMENT,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as out:
            out.write(rendered);out.flush();os.fchown(out.fileno(),0,caddy_gid);os.fchmod(out.fileno(),0o640);os.fsync(out.fileno())
        sync_directory(FRAGMENT.parent)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Préparer les connexions Voice sans activer les appels.')
    parser.add_argument('action',choices=['prepare','read-gateway','enable-hooks'])
    args=parser.parse_args(argv)
    try:
        if os.geteuid()!=0:raise PreflightError('Exécutez cet outil en root.')
        fd=os.open('/run/lock/unlimited-talk-staging-deploy.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            base=voice.load_base();plan=voice.validate_plan(read_private(voice.PLAN),base)
            config=voice.validate_credentials(read_private(voice.CREDENTIALS),plan,base)
            prepare(config)
            if args.action=='read-gateway':
                original=CADDY.read_text();line='import '+str(FRAGMENT)+'\n'
                if line not in original:
                    replace_caddy(original.rstrip()+'\n\n'+line)
                directory=Path('/etc/systemd/system/caddy.service.d');directory.mkdir(mode=0o755,exist_ok=True)
                dropin=directory/'unlimited-talk-voice.conf'
                value='[Unit]\nAfter=docker.service\nWants=docker.service\n'
                if dropin.exists() and dropin.read_text()!=value:raise PreflightError('Ordre de démarrage différent ; examen requis.')
                if not dropin.exists():
                    dropin.write_text(value);dropin.chmod(0o644)
                    subprocess.run(['systemctl','daemon-reload'],capture_output=True,check=True,timeout=15)
            elif args.action=='enable-hooks':
                with urllib.request.urlopen('http://127.0.0.1:8110/health/ready',timeout=8) as response:health=json.load(response)
                if health.get('communications')!='webhooks_only' or health.get('calling_enabled') is not False:
                    raise PreflightError('Déployez d’abord la réception signée sans appels.')
                original=CADDY.read_text();candidate=render_hooks(original)
                if candidate!=original:replace_caddy(candidate)
        print(json.dumps({'prepared':True,'action':args.action,'calling_enabled':False}))
        return 0
    except PreflightError as error:print(str(error),file=sys.stderr)
    except Exception:print('Préparation interrompue. Aucun secret affiché ; configuration à vérifier.',file=sys.stderr)
    return 1


if __name__=='__main__':raise SystemExit(main())

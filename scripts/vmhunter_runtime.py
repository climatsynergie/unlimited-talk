"""Root operator for the optional VM Hunter runtime; never originates calls.

Uses only the existing attested image. Stages with a disabled policy, grants
HTTPS egress only to its fixed container address and approved provider IPs, and
reuses the installed call-drain/enable operator before API mount changes.
"""
import argparse
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time
import urllib.request


ROOT = Path('/etc/unlimited-talk-staging')
BASE = Path('/srv/unlimited-talk-staging')
STATE = ROOT / 'vmhunter-runtime'
POLICY = ROOT / 'vmhunter-campaign-policy.json'
CREDENTIALS = ROOT / 'container-secrets/vmhunter_credentials'
ADDRESS = '172.30.8.240'
CHAIN = 'UT-VMHUNTER-EGRESS'
HOSTS = ('app.vmhunter.com', 'api.twilio.com')
DEPLOYER_SHA = '3f12ea6d195c9843b81b5125146d2cf225831b08da574dc5e2dd887fd947e107'
MEDIA = '''    location = /api/telephony/vmhunter/media {
        limit_except GET { deny all; }
        access_log off;
        set $observer http://vmhunter:8080;
        proxy_pass $observer;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_connect_timeout 2s;
        proxy_read_timeout 12s;
        proxy_send_timeout 5s;
        proxy_buffering off;
    }
'''


def run(command, *, data=None, timeout=120):
    p = subprocess.run(command, input=data, text=True, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError('Runtime command failed: ' + command[0] + ' ' + command[1])
    return p.stdout.strip()


def checked_private(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) not in {0o600, 0o440}):
        raise ValueError('Private regular root-owned file required')
    return path.read_bytes()


def write_file(path, data, mode=0o600, group=0):
    """Preserve the inode: Docker bind mounts must see policy/NGINX updates."""
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise ValueError('Unexpected target file')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        os.fchown(stream.fileno(), 0, group)
        os.fchmod(stream.fileno(), mode)
        stream.write(data); stream.truncate(); stream.flush(); os.fsync(stream.fileno())


def patched_compose(value):
    value = json.loads(json.dumps(value))
    api = value['services']['api']
    api['environment']['VMHUNTER_PILOT_FILE'] = '/run/secrets/vmhunter_pilot'
    if 'vmhunter_pilot' not in api['secrets']:
        api['secrets'].append('vmhunter_pilot')
    value['secrets']['vmhunter_pilot'] = {'file': str(POLICY)}
    return value


def patched_gateway(value):
    if 'location = /api/telephony/vmhunter/media {' in value:
        if value.count('location = /api/telephony/vmhunter/media {') != 1:
            raise ValueError('Ambiguous media gateway')
        return value
    marker = '    resolver 127.0.0.11 valid=5s ipv6=off;\n'
    if value.count(marker) != 1:
        raise ValueError('Unexpected gateway layout')
    return value.replace(marker, marker + MEDIA)


def provider_addresses(resolve=socket.getaddrinfo):
    addresses = set()
    for host in HOSTS:
        found = {row[4][0] for row in resolve(host, 443, socket.AF_INET, socket.SOCK_STREAM)}
        if not found or any(not ipaddress.IPv4Address(ip).is_global for ip in found):
            raise ValueError('Public provider IPv4 resolution required')
        addresses.update(found)
    return sorted(addresses)


def refresh_egress():
    addresses = provider_addresses()
    if subprocess.run(['iptables', '-S', CHAIN], capture_output=True).returncode:
        run(['iptables', '-N', CHAIN])
    # This child chain is reached only by the dedicated VM container /32.
    desired = [['-d', address + '/32', '-p', 'tcp', '--dport', '443', '-j', 'ACCEPT'] for address in addresses]
    for rule in desired:
        if subprocess.run(['iptables', '-C', CHAIN, *rule], capture_output=True).returncode:
            run(['iptables', '-I', CHAIN, '1', *rule])
    import shlex
    for line in run(['iptables', '-S', CHAIN]).splitlines():
        pieces = shlex.split(line)
        if pieces[:2] == ['-A', CHAIN] and pieces[2:] != ['-j', 'RETURN']:
            # Remove only old rules created by this provider-specific chain.
            address = pieces[pieces.index('-d') + 1] if '-d' in pieces else None
            if address not in {a + '/32' for a in addresses}:
                run(['iptables', '-D', CHAIN, *pieces[2:]])
    if subprocess.run(['iptables', '-C', CHAIN, '-j', 'RETURN'], capture_output=True).returncode:
        run(['iptables', '-A', CHAIN, '-j', 'RETURN'])
    jump = ['-s', ADDRESS + '/32', '-j', CHAIN]
    if subprocess.run(['iptables', '-C', 'UT-STAGING-EGRESS', *jump], capture_output=True).returncode:
        run(['iptables', '-I', 'UT-STAGING-EGRESS', '1', *jump])
    print(json.dumps({'step': 'scoped_egress', 'provider_addresses': len(addresses), 'source': ADDRESS}), flush=True)


def installed_deployer():
    path = Path('/usr/local/sbin/unlimited-talk-staging-deploy')
    if hashlib.sha256(checked_private_deployer(path)).hexdigest() != DEPLOYER_SHA:
        raise ValueError('Installed deployer changed; review required')
    loader = importlib.machinery.SourceFileLoader('reviewed_deployer', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    return module


def checked_private_deployer(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('Protected installed deployer required')
    return path.read_bytes()


def app_command(release):
    return ['docker', 'compose', '--project-directory', str(release), '--env-file',
            str(release / '.env'), '-f', str(release / 'compose.managed.yaml')]


def vm_command(release):
    return ['docker', 'compose', '--project-directory', str(STATE), '--env-file',
            str(release / '.env'), '-f', str(STATE / 'compose.json')]


def environment(release):
    return json.loads(run([*app_command(release), 'config', '--format', 'json']))


def standalone(config):
    image = config['services']['api']['image']
    if not re.fullmatch(r'ghcr.io/climatsynergie/unlimited-talk-api@sha256:[a-f0-9]{64}', image):
        raise ValueError('Attested immutable image required')
    env = dict(config['services']['api']['environment'])
    for key in ('IDENTITY_KEY_FILE', 'SPACES_CONFIG_FILE'):
        env.pop(key, None)
    env.update(COMMUNICATIONS_MODE='webhooks_only', VMHUNTER_PILOT_FILE='/run/secrets/vmhunter_pilot',
               VMHUNTER_CREDENTIALS_FILE='/run/secrets/vmhunter_credentials')
    names = ('postgres_ca', 'runtime_password', 'voice_profile', 'vmhunter_pilot', 'vmhunter_credentials')
    secrets = {k: config['secrets'][k] for k in names[:3]}
    secrets.update(vmhunter_pilot={'file': str(POLICY)}, vmhunter_credentials={'file': str(CREDENTIALS)})
    service = dict(image=image, pull_policy='never', user='10001:10001', read_only=True,
        tmpfs=['/tmp:rw,noexec,nosuid,size=32m'], cap_drop=['ALL'], security_opt=['no-new-privileges:true'],
        restart='unless-stopped', command=['python', '-m', 'app.telephony.vmhunter_observer'],
        environment=env, secrets=list(names), mem_limit='256m', cpus=0.5, pids_limit=64,
        networks={'staging': {'ipv4_address': ADDRESS, 'aliases': ['vmhunter']}},
        logging={'driver': 'local', 'options': {'max-size': '5m', 'max-file': '2'}},
        healthcheck={'test': ['CMD', 'python', '-c', "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live',timeout=3)"],
                     'interval': '5s', 'timeout': '4s', 'retries': 6})
    return dict(name='unlimited-talk-vmhunter', services={'vmhunter': service}, secrets=secrets,
                networks={'staging': {'external': True, 'name': config['networks']['staging']['name']}})


def vm_exec(release, program):
    return run([*vm_command(release), 'exec', '-T', 'vmhunter', 'python', '-'], data=program, timeout=50)


def stage(release):
    config = environment(release)
    manifest = json.loads(checked_private(release / 'deployment.json'))
    assert manifest['image'] == config['services']['api']['image']
    network = json.loads(run(['docker', 'network', 'inspect', config['networks']['staging']['name']]))[0]
    for container in network['Containers'].values():
        if container['IPv4Address'].split('/')[0] == ADDRESS and not container['Name'].startswith('unlimited-talk-vmhunter-'):
            raise ValueError('Dedicated VM address already occupied')
    value = json.loads(checked_private(POLICY))
    assert value['version'] == 3 and value['scope'] == 'campaign' and value['audio_approved'] is True and value['screening_approved'] is True
    assert value['campaign_id'] == '2bdf5195-0b52-49b1-aecc-0caaf5459e77'
    value['enabled'] = False
    write_file(POLICY, (json.dumps(value) + '\n').encode(), 0o440, 10001)
    raw = checked_private(ROOT / 'vmhunter-credentials.json')
    credentials = json.loads(raw)
    assert set(credentials) == {'version', 'mode', 'endpoint', 'api_key'}
    assert credentials['endpoint'] == 'wss://app.vmhunter.com/ws' and credentials['api_key']
    write_file(CREDENTIALS, raw, 0o440, 10001)
    STATE.mkdir(mode=0o700, exist_ok=True)
    write_file(STATE / 'compose.json', (json.dumps(standalone(config), indent=2) + '\n').encode())
    refresh_egress()
    run([*vm_command(release), 'up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '90'], timeout=110)
    proof = json.loads(vm_exec(release, "import json,urllib.request\nwith urllib.request.urlopen('http://127.0.0.1:8080/health/live') as r:print(json.dumps(json.load(r)))"))
    assert proof['accepting'] is False
    print(json.dumps({'step': 'standby_healthy', 'accepting': False}), flush=True)


def probe(release):
    program = '''import asyncio,json,socket,ssl,urllib.request
from app.telephony.vmhunter_observer import runtime
from app.telephony.configuration import load_profile
from app.database import make_engine
from app.identity.service import query
from app.telephony import vmhunter as vm
import aiohttp
async def main():
    for host in ('app.vmhunter.com','api.twilio.com'):
        with socket.create_connection((host,443),timeout=4) as raw:
            with ssl.create_default_context().wrap_socket(raw,server_hostname=host):pass
    profile=load_profile()
    engine=make_engine()
    with engine.connect() as db:
        query(db,'SET TRANSACTION READ ONLY')
        child=query(db,"SELECT child_call_sid FROM staging.voice_intents WHERE campaign_id=:campaign AND child_call_sid IS NOT NULL ORDER BY created_at DESC LIMIT 1",campaign=vm.PILOT_CAMPAIGN).scalar_one()
    engine.dispose()
    async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=12)) as session:
        url='https://api.twilio.com/2010-04-01/Accounts/'+profile.account_sid+'/Calls/'+child+'.json'
        async with session.get(url,auth=aiohttp.BasicAuth(profile.api_key_sid,profile.api_key_secret)) as response:
            assert response.status==200,'Twilio account authentication failed'
            result=await response.json();assert result.get('sid')==child and result.get('account_sid')==profile.account_sid
        import os
        from app.telephony.configuration import private_bytes
        credentials=json.loads(private_bytes(os.environ['VMHUNTER_CREDENTIALS_FILE']))
        async def frames():
            for _ in range(175):
                yield bytes(320)
        result=await vm.Client(credentials['api_key'],session=session).classify('runtime-synthetic-probe',frames())
        print(json.dumps(dict(tls=True,twilio_account_authenticated=True,provider_authenticated=result.status in {'HUMAN','MACHINE','CALLGUARD'},synthetic_result={'status':result.status,'cause':result.cause},real_calls=0)))
asyncio.run(main())
'''
    proof=json.loads(vm_exec(release, program))
    print(json.dumps(proof), flush=True)
    if not proof['provider_authenticated']:raise ValueError('Provider synthetic analysis did not succeed')


def activate(release):
    import yaml
    module = installed_deployer()
    before = module.calling_state(release)
    if not before['calling_enabled']:
        raise ValueError('Expected previously enabled calls')
    module.require_idle_calls(release)
    config = environment(release)
    current = release / 'compose.managed.yaml'
    template = ROOT / 'deployment-template/compose.managed.yaml'
    gateways = [release / 'scripts/nginx.conf', ROOT / 'deployment-template/nginx.conf']
    originals = {p: p.read_bytes() for p in (current, template, *gateways)}
    STATE.mkdir(mode=0o700, exist_ok=True)
    for index, (p, raw) in enumerate(originals.items()):
        backup = STATE / ('before-activation-' + str(index))
        if not backup.exists(): write_file(backup, raw)
    # Every original/candidate is parsed and validated before closing calls.
    candidates = {p: yaml.safe_dump(patched_compose(yaml.safe_load(raw)),sort_keys=False).encode()
                  for p, raw in originals.items() if p in (current,template)}
    candidates.update({p: patched_gateway(originals[p].decode()).encode() for p in gateways})
    candidate = STATE / 'candidate.compose.yaml'; write_file(candidate, candidates[current])
    check = json.loads(run(['docker','compose','--project-directory',str(release),'--env-file',str(release/'.env'),'-f',str(candidate),'config','--format','json']))
    expected = json.loads(json.dumps(config))
    expected['services']['api']['environment']['VMHUNTER_PILOT_FILE']='/run/secrets/vmhunter_pilot'
    expected['services']['api']['secrets'].append({'source':'vmhunter_pilot','target':'/run/secrets/vmhunter_pilot'})
    expected['secrets']['vmhunter_pilot']={'name':config['name']+'_vmhunter_pilot','file':str(POLICY)}
    assert check==expected,'Only the reviewed API policy mount may change'
    closed = False
    try:
        closed = True
        module.require_idle_calls(release)
        module.calling_action('disable', before['revision'])
        module.require_idle_calls(release)
        for p, raw in candidates.items(): write_file(p,raw,0o644 if p in gateways else 0o600)
        gateway = run([*app_command(release),'ps','-q','gateway'])
        run(['docker','exec',gateway,'nginx','-t'])
        run(['docker','exec',gateway,'nginx','-s','reload'])
        value=json.loads(checked_private(POLICY));value['enabled']=True
        write_file(POLICY,(json.dumps(value)+'\n').encode(),0o440,10001)
        run([*vm_command(release),'up','-d','--force-recreate','--wait','--wait-timeout','60'],timeout=90)
        proof=json.loads(vm_exec(release,"import json,urllib.request\nwith urllib.request.urlopen('http://127.0.0.1:8080/health/live') as r:print(json.dumps(json.load(r)))"))
        assert proof['accepting'] is True
        module.calling_action('enable', before['revision']); closed = False
        state=module.calling_state(release)
        assert state['calling_enabled']
        print(json.dumps({'step':'activated','revision':state['revision'],'calling_enabled':True,'campaign_id':value['campaign_id'],'scope':value['scope'],'max_analyses':value['max_analyses']}),flush=True)
    except Exception:
        value=json.loads(checked_private(POLICY));value['enabled']=False
        write_file(POLICY,(json.dumps(value)+'\n').encode(),0o440,10001)
        if closed:
            for p, raw in originals.items():write_file(p,raw,0o644 if p in gateways else 0o600)
            gateway=run([*app_command(release),'ps','-q','gateway'])
            run(['docker','exec',gateway,'nginx','-t']);run(['docker','exec',gateway,'nginx','-s','reload'])
            module.calling_action('enable',before['revision'])
        raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['stage','probe','activate','refresh-egress'])
    args=parser.parse_args()
    if os.geteuid()!=0:raise ValueError('Root operator required')
    os.umask(0o077)
    if args.action=='refresh-egress':refresh_egress();return
    with open('/run/lock/unlimited-talk-staging-deploy.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        release=(BASE/'current').resolve(strict=True)
        if release.parent!=BASE/'releases':raise ValueError('Unexpected release')
        {'stage':stage,'probe':probe,'activate':activate}[args.action](release)


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'runtime_operation':'stopped','error_type':type(error).__name__}),flush=True)
        raise SystemExit(1)

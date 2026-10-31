"""Apply only the verified Voice prefix Rule, with durable no-repeat recovery.

No DEFAULT, PATCH, DELETE, phone routing, call or SMS operation is allowed.
An accepted write is complete only after its propagation Operation is COMPLETED.
"""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import re
import ssl
import sys
import time
import urllib.request

import twilio_voice_preflight as voice
import twilio_voice_signing as signing
from twilio_voice_application import save
from twilio_voice_delivery_test import delivery_code
from staging_twilio_preflight import NoRedirect, PreflightError, read_private

JOURNAL = signing.JOURNAL.with_name('twilio-voice-rule.json')
OP_PREFIX = 'webhooks_operation_'
FIELDS = {'version','binding','state','rule_id','operation_id','rule_fingerprint',
          'proof_name','proof_digest','requested_at','next_check_at'}


class Provider:
    def __init__(self, config, setting_id, send=None):
        self.config,self.setting_id,self.send = config,setting_id,send
        self.signing = signing.Provider(config, send)

    def inventory(self):
        return self.signing.inventory()

    def request(self, method, path, body=None):
        allowed = (method == 'POST' and path == '/Rules' and body == signing.route_setting(self.setting_id))
        allowed |= (method == 'GET' and body is None and bool(re.fullmatch(
            r'/Operations/webhooks_operation_[A-Za-z0-9]{26}|/Operations\?resourceId=webhooks_rule_[A-Za-z0-9]{26}',path)))
        if not allowed:
            raise PreflightError('Opération de route refusée.')
        auth=base64.b64encode((self.config['api_key_sid']+':'+self.config['api_key_secret']).encode()).decode()
        request=urllib.request.Request('https://webhooks.twilio.com/v1/Webhooks'+path,
            method=method,data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization':'Basic '+auth,'Content-Type':'application/json','Accept':'application/json'})
        if self.send is not None:
            return self.send(request)
        opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(request,timeout=15) as response:
            if response.status != (202 if method=='POST' else 200):
                raise PreflightError('Réponse de route inattendue.')
            raw=response.read(65537)
            metadata={'operation_id':response.headers.get('Operation-Id'),
                      'retry_after':response.headers.get('Retry-After','5')}
        if len(raw)>65536:raise PreflightError('Réponse de route trop volumineuse.')
        return json.loads(raw),metadata


def proof(path, now):
    if not re.fullmatch(r'voice-delivery-[0-9]{8}T[0-9]{12}\.json',path.name):
        raise PreflightError('Nom du reçu de livraison invalide.')
    data=read_private(path)
    result=data.get('result',{})
    if (data.get('url')!=signing.RULE_PREFIX+'probe' or result.get('outcome')!='DELIVERED'
            or delivery_code(result.get('response'))!=204):
        raise PreflightError('Une livraison signée 204 est requise avant la route.')
    # The private file is created only after the bounded Tests request. Its
    # freshness is checked locally, independent of provider timestamp formatting.
    if not 0 <= now-path.stat().st_mtime <= 900:
        raise PreflightError('Le contrôle de livraison doit dater de moins de quinze minutes.')
    return signing.digest(data)


def matching(inventory, setting_id):
    desired=signing.route_setting(setting_id)
    return [row for row in inventory['Rules'].values() if all(row.get(k)==v for k,v in desired.items())]


def run(action, config, *, path=JOURNAL, receipt=None, provider=None, now=None):
    now=time.time() if now is None else now
    source=read_private(signing.JOURNAL)
    if source['state']!='verified' or source['binding']!=signing.binding(config):
        raise PreflightError('Le plan de signature doit être vérifié.')
    provider=Provider(config,source['setting_id']) if provider is None else provider
    inventory=provider.inventory()
    key=signing.validate_key(read_private(signing.KEY))
    actual=provider.signing.request('GET','/Settings/'+source['setting_id'])
    signing.validate_setting(actual,key['id'])
    if key['id']!=source['key_id'] or actual['id']!=source['setting_id']:
        raise PreflightError('Clé ou paramétrage différent du plan.')
    if action=='prepare' and not path.exists():
        signing.preserved(source,inventory)
        if receipt is None:raise PreflightError('Fournissez le reçu de livraison vérifié.')
        if (any(row.get('prefix')==signing.RULE_PREFIX or row.get('friendlyName')==signing.RULE_NAME
                for row in inventory['Rules'].values())):
            raise PreflightError('Cette route existe déjà ; aucune adoption automatique.')
        state=dict(version=1,binding=source['binding'],state='prepared',rule_id=None,operation_id=None,
            rule_fingerprint=None,proof_name=receipt.name,proof_digest=proof(receipt,now),requested_at=None,next_check_at=0)
        save(state,path)
    else:
        state=read_private(path)
        if (set(state)!=FIELDS or state['version']!=1 or state['binding']!=source['binding']
                or state['state'] not in {'prepared','requested','propagating','verified'}):
            raise PreflightError('Journal de route invalide.')
    if state['state']=='prepared':
        signing.preserved(source,inventory)
        if action=='apply':
            receipt=path.with_name(state['proof_name'])
            if proof(receipt,now)!=state['proof_digest']:
                raise PreflightError('Le reçu de livraison a changé.')
            state.update(state='requested',requested_at=now)
            save(state,path,replace=True)
            data,metadata=provider.request('POST','/Rules',signing.route_setting(source['setting_id']))
            operation_id=metadata.get('operation_id')
            if not signing.identifier(operation_id,OP_PREFIX):
                raise PreflightError('Réponse de création incertaine ; aucun nouvel envoi.')
            retry=metadata.get('retry_after','5')
            retry=int(retry) if str(retry).isdigit() else 5
            state.update(operation_id=operation_id,next_check_at=now+max(1,min(90,retry)))
            save(state,path,replace=True)
            inventory=provider.inventory()
    if state['state']=='requested':
        # After a timeout or crash, list and reconcile. Never repeat the POST.
        found=matching(inventory,source['setting_id'])
        if len(found)!=1 or found[0]['id'] in source['before']['Rules']:
            raise PreflightError('Création de route incertaine ; aucun nouvel envoi.')
        row=found[0]
        if state['operation_id'] is None:
            data,_=provider.request('GET','/Operations?resourceId='+row['id'])
            if (not isinstance(data.get('meta'),dict) or data['meta'].get('nextToken') not in (None,'')
                    or 'nextToken' not in data['meta'] or not isinstance(data.get('operations'),list)):
                raise PreflightError('Inventaire des opérations incomplet.')
            operations=[o for o in data['operations'] if o.get('resourceId')==row['id']]
            if len(operations)!=1 or not signing.identifier(operations[0].get('id'),OP_PREFIX):
                raise PreflightError('Opération de création ambiguë ; examen requis.')
            state['operation_id']=operations[0]['id']
        state.update(state='propagating',rule_id=row['id'],
            rule_fingerprint=signing.fingerprints({row['id']:row})[row['id']])
        signing.preserved(source,inventory,state)
        save(state,path,replace=True)
    if state['state'] in {'propagating','verified'}:
        signing.preserved(source,inventory,state)
        if state['state']=='propagating' and now>=state['next_check_at']:
            data,metadata=provider.request('GET','/Operations/'+state['operation_id'])
            operation=data.get('operation',data)
            if operation.get('id')!=state['operation_id'] or operation.get('resourceId')!=state['rule_id']:
                raise PreflightError('Opération différente de la route attendue.')
            status=operation.get('status')
            if status=='COMPLETED':state['state']='verified'
            elif status not in {'PENDING','RUNNING'}:
                raise PreflightError('La propagation a échoué ; examen requis.')
            state['next_check_at']=now+5
            save(state,path,replace=True)
    return {'state':state['state'],'rule_id':state['rule_id'],'operation_id':state['operation_id'],
            'next_check_in_seconds':max(0,int(state['next_check_at']-now)),
            'legacy_rules_preserved':True,'calling_enabled':False}


def main():
    parser=argparse.ArgumentParser(description='Appliquer uniquement la route Voice signée et testée.')
    parser.add_argument('action',choices=['prepare','apply','check'])
    parser.add_argument('--receipt')
    args=parser.parse_args()
    if os.geteuid()!=0:raise PreflightError('Exécutez cet outil en root.')
    with open('/run/lock/unlimited-talk-staging-deploy.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with urllib.request.urlopen('http://127.0.0.1:8110/health/ready',timeout=8) as response:health=json.load(response)
        if health.get('communications')!='webhooks_only' or health.get('calling_enabled') is not False:
            raise PreflightError('La réception signée sans appels doit être saine.')
        base=voice.load_base();plan=voice.validate_plan(read_private(voice.PLAN),base)
        config=voice.validate_credentials(read_private(voice.CREDENTIALS),plan,base)
        receipt=None
        if args.receipt:
            if Path(args.receipt).name!=args.receipt:raise PreflightError('Utilisez seulement le nom du reçu privé.')
            receipt=JOURNAL.with_name(args.receipt)
        print(json.dumps(run(args.action,config,receipt=receipt)))


if __name__=='__main__':
    try:main()
    except PreflightError as error:print(str(error),file=sys.stderr);raise SystemExit(1)
    except Exception:print('Route interrompue ; aucun secret affiché. Reprenez en lecture avec check.',file=sys.stderr);raise SystemExit(1)

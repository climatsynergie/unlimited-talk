"""Root-only credential entry and read-only Twilio number verification.

Never creates calls, messages, trunks, numbers or routing changes. Kept outside
application containers; only a selected IncomingPhoneNumber resource is read.
"""
import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import re
import ssl
import stat
import sys
import urllib.error
import urllib.request
import warnings

CONFIG=Path('/etc/unlimited-talk-staging/twilio-preflight.json')
FIELDS={'version','mode','region','account_sid','api_key_sid','api_key_secret','phone_number_sid','caller_number'}


class PreflightError(Exception):
    pass


def validate(config):
    if not isinstance(config,dict) or set(config)!=FIELDS or type(config['version']) is not int or config['version']!=1:
        raise PreflightError('Format de configuration Twilio invalide.')
    if config['mode']!='read_only' or config['region']!='us1':
        raise PreflightError('Cette vérification nécessite le mode lecture seule et la région US1.')
    for field,prefix in [('account_sid','AC'),('api_key_sid','SK'),('phone_number_sid','PN')]:
        if not isinstance(config[field],str) or not re.fullmatch(prefix+r'[0-9a-fA-F]{32}',config[field]):
            raise PreflightError('Format SID invalide : '+field+'.')
    secret=config['api_key_secret']
    if not isinstance(secret,str) or not 32<=len(secret)<=256 or not secret.isascii() or not secret.isprintable() or any(c.isspace() for c in secret):
        raise PreflightError('Format du secret de la clé API invalide.')
    if not isinstance(config['caller_number'],str) or not re.fullmatch(r'\+[1-9][0-9]{8,14}',config['caller_number']):
        raise PreflightError('Le numéro Twilio doit être au format international, par exemple +14165550100.')
    return config


def private_parent(path):
    parent=path.parent
    info=parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o077:
        raise PreflightError('Le dossier de configuration doit être privé et appartenir à l’utilisateur courant.')


def store(config,path=CONFIG):
    validate(config);private_parent(path)
    # O_EXCL refuses an existing file, including symbolic links. Never overwrite.
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(config,stream);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def load(path=CONFIG):
    private_parent(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:
            raise PreflightError('Le fichier de configuration doit être privé, régulier et en mode 600.')
        raw=stream.read(8193)
        if len(raw)>8192:raise PreflightError('Le fichier de configuration est trop volumineux.')
    try:config=json.loads(raw)
    except (ValueError,UnicodeError):raise PreflightError('Le fichier de configuration est invalide.') from None
    return validate(config)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise PreflightError('Redirection HTTPS refusée lors de la vérification Twilio.')


def transport(request):
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request,timeout=12) as response:
        raw=response.read(65537)
        if len(raw)>65536:raise PreflightError('Réponse Twilio trop volumineuse.')
        try:return json.loads(raw)
        except (ValueError,UnicodeError):raise PreflightError('Réponse Twilio invalide.') from None


def check(config,send=transport):
    validate(config)
    url='https://api.twilio.com/2010-04-01/Accounts/'+config['account_sid']+'/IncomingPhoneNumbers/'+config['phone_number_sid']+'.json'
    token=base64.b64encode((config['api_key_sid']+':'+config['api_key_secret']).encode()).decode()
    request=urllib.request.Request(url,headers={'Authorization':'Basic '+token,'Accept':'application/json','User-Agent':'Unlimited-Talks-readonly-preflight/1'},method='GET')
    try:data=send(request)
    except urllib.error.HTTPError as error:
        messages={401:'Authentification Twilio refusée. Vérifiez la clé, son secret et la région.',403:'Accès refusé. Vérifiez la permission de lecture du numéro.',404:'Numéro introuvable dans ce compte. Vérifiez les SID du compte et du numéro.',429:'Twilio limite les requêtes. Réessayez plus tard.'}
        raise PreflightError(messages.get(error.code,'La lecture du numéro Twilio a échoué.')) from None
    if not isinstance(data,dict) or data.get('account_sid')!=config['account_sid'] or data.get('sid')!=config['phone_number_sid'] or data.get('phone_number')!=config['caller_number']:
        raise PreflightError('La réponse Twilio ne correspond pas au compte et au numéro configurés.')
    capabilities=data.get('capabilities')
    if not isinstance(capabilities,dict):raise PreflightError('Capacités du numéro Twilio absentes.')
    return {'status':'number_read_verified','caller_last_four':config['caller_number'][-4:],
            'voice_capability':capabilities.get('voice') is True,'sms_capability':capabilities.get('sms') is True,
            'sip_trunk_assigned':bool(data.get('trunk_sid')),
            'existing_inbound_route':bool(data.get('voice_url') or data.get('voice_application_sid') or data.get('trunk_sid')),
            'live_call_verified':False,'configuration_changed':False}


def collect(prompt=getpass.getpass):
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        config={'version':1,'mode':'read_only','region':'us1'}
        for field,label in [('account_sid','Account SID Twilio (AC…, invisible) : '),('api_key_sid','SID de la clé API limitée (SK…, invisible) : '),('api_key_secret','Secret de la clé API (invisible) : ')]:
            config[field]=prompt(label).strip()
        confirmation=prompt('Confirmez le secret de la clé API : ').strip()
        if config['api_key_secret']!=confirmation:raise PreflightError('Les secrets sont différents. Aucun enregistrement.')
        config['phone_number_sid']=prompt('SID du numéro Twilio (PN…, invisible) : ').strip()
        config['caller_number']=prompt('Numéro Twilio international (+1…, invisible) : ').strip()
        return validate(config)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Préparation Twilio en lecture seule, sans appel ni modification du compte.')
    parser.add_argument('action',choices=['store','check'])
    args=parser.parse_args(argv)
    try:
        if os.geteuid()!=0:raise PreflightError('Exécutez cet outil dans le terminal root du serveur staging.')
        if args.action=='store':
            if CONFIG.exists() or CONFIG.is_symlink():raise PreflightError('Une configuration existe déjà. Elle reste inchangée.')
            private_parent(CONFIG)
            store(collect())
            print('Identifiants enregistrés dans un fichier privé. La connexion reste à vérifier.');return 0
        result=check(load())
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['voice_capability'] else 1
    except FileNotFoundError:
        print('Configuration Twilio absente. Exécutez d’abord la commande store.',file=sys.stderr)
    except FileExistsError:
        print('Une configuration existe déjà. Elle reste inchangée.',file=sys.stderr)
    except (EOFError,KeyboardInterrupt,getpass.GetPassWarning):
        print('Saisie interrompue. Utilisez un terminal interactif ; aucun secret n’est affiché.',file=sys.stderr)
    except PreflightError as error:print(str(error),file=sys.stderr)
    except Exception:
        print('Vérification interrompue. Les identifiants ne sont pas affichés ; vérifiez les permissions du fichier et la connexion HTTPS.',file=sys.stderr)
    return 1


if __name__=='__main__':raise SystemExit(main())

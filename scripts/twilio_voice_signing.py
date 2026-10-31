"""Provision a private signing key and inactive Setting; never change Rules.

Every POST is journaled before sending. A lost key response cannot be recovered
and must never cause an automatic second creation. No calls, phone/application
updates, existing key edits or account-wide signing changes are permitted.
"""
import argparse
import base64
import fcntl
import json
import os
import re
import ssl
import stat
import sys
import urllib.request

import twilio_voice_preflight as voice
from staging_twilio_preflight import NoRedirect, PreflightError, read_private, write_private
from twilio_voice_application import binding, digest, save, validate_journal as application_journal

JOURNAL = voice.PLAN.with_name('twilio-voice-signing.json')
KEY = voice.PLAN.with_name('twilio-voice-signing-key.json')
PROFILE = voice.PLAN.with_name('twilio-voice-profile.json')
NAME = 'unlimited-talk-voice-signature'
RESOURCES = {'SharedKeys': ('sharedKeys', 'webhooks_sharedkey_'), 'Settings': ('settings', 'webhooks_setting_'),
             'Rules': ('rules', 'webhooks_rule_')}


def identifier(value, prefix):
    return isinstance(value, str) and re.fullmatch(prefix + r'[A-Za-z0-9]{26}', value) is not None


def setting(key_id):
    return {'friendlyName': NAME, 'auth': {'source': 'INLINE', 'value': {'scheme': 'NONE'}},
            'signature': {'type': 'SHARED_KEY', 'sharedKeyId': key_id, 'algorithm': 'HMAC_SHA1'}}


class Provider:
    def __init__(self, config, send=None):
        self.config, self.send = config, send

    def request(self, method, path, body=None):
        allowed = bool(method == 'GET' and (path in ('/SharedKeys', '/Settings', '/Rules')
                   or re.fullmatch(r'/(SharedKeys/webhooks_sharedkey_|Settings/webhooks_setting_)[A-Za-z0-9]{26}', path)))
        allowed |= (method == 'POST' and path == '/SharedKeys' and body == {'friendlyName': NAME})
        allowed |= (method == 'POST' and path == '/Settings' and isinstance(body, dict)
                    and isinstance(body.get('signature'), dict)
                    and identifier(body['signature'].get('sharedKeyId'), 'webhooks_sharedkey_')
                    and body == setting(body['signature']['sharedKeyId']))
        if not allowed or (method == 'GET' and body is not None):
            raise PreflightError('Opération de signature refusée.')
        auth = base64.b64encode((self.config['api_key_sid'] + ':' + self.config['api_key_secret']).encode()).decode()
        request = urllib.request.Request('https://webhooks.twilio.com/v1/Webhooks' + path,
            data=json.dumps(body).encode() if body is not None else None, method=method,
            headers={'Authorization': 'Basic ' + auth, 'Accept': 'application/json', 'Content-Type': 'application/json'})
        if self.send is not None:
            return self.send(request)
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(request, timeout=15) as response:
            if response.status != (201 if method == 'POST' else 200):
                raise PreflightError('Réponse de signature inattendue.')
            raw = response.read(65537)
        if len(raw) > 65536:
            raise PreflightError('Réponse de signature trop volumineuse.')
        return json.loads(raw)

    def inventory(self):
        result = {}
        for resource, (field, prefix) in RESOURCES.items():
            data = self.request('GET', '/' + resource)
            if (not isinstance(data, dict) or not isinstance(data.get('meta'), dict)
                    or 'nextToken' not in data['meta'] or data['meta']['nextToken'] not in (None, '')
                    or not isinstance(data.get(field), list)):
                raise PreflightError('Inventaire de signature incomplet.')
            rows = {}
            for row in data[field]:
                if not isinstance(row, dict) or not identifier(row.get('id'), prefix) or row['id'] in rows:
                    raise PreflightError('Identité de signature invalide.')
                rows[row['id']] = row
            result[resource] = rows
        return result


def fingerprints(rows):
    return {key: digest({k: v for k, v in row.items() if k not in {'createdAt', 'updatedAt'}}) for key, row in rows.items()}


def preserved(journal, inventory):
    for resource in RESOURCES:
        current = {key: row for key, row in inventory[resource].items()
                   if key not in {journal.get('key_id'), journal.get('setting_id')}}
        if fingerprints(current) != journal['before'][resource]:
            raise PreflightError('La configuration de signature existante a changé ; examen requis.')


def validate_key(key):
    if (not isinstance(key, dict) or set(key) != {'id', 'secret', 'friendlyName'}
            or not identifier(key['id'], 'webhooks_sharedkey_') or key['friendlyName'] != NAME
            or not isinstance(key['secret'], str) or not 32 <= len(key['secret']) <= 256
            or not key['secret'].isascii() or not key['secret'].isprintable() or any(c.isspace() for c in key['secret'])):
        raise PreflightError('Clé de signature privée invalide.')
    return key


def validate_setting(value, key_id):
    if (not isinstance(value, dict) or not identifier(value.get('id'), 'webhooks_setting_')
            or any(value.get(key) != expected for key, expected in setting(key_id).items())):
        raise PreflightError('Le paramétrage de signature ne correspond pas au plan.')
    return value


def run(action, config, path=JOURNAL, key_path=KEY, provider=None):
    provider = Provider(config) if provider is None else provider
    inventory = provider.inventory()
    if action == 'prepare' and not (path.exists() or path.is_symlink()):
        if any(row.get('friendlyName') == NAME for resource in RESOURCES for row in inventory[resource].values()):
            raise PreflightError('Un paramétrage porte déjà ce nom. Aucun remplacement automatique.')
        journal = {'version': 1, 'binding': binding(config), 'state': 'prepared', 'key_id': None, 'setting_id': None,
                   'before': {resource: fingerprints(rows) for resource, rows in inventory.items()}}
        save(journal, path)
    else:
        journal = read_private(path)
        if (not isinstance(journal, dict) or set(journal) != {'version','binding','state','key_id','setting_id','before'}
                or type(journal['version']) is not int or journal['version'] != 1 or journal['binding'] != binding(config)
                or journal['state'] not in {'prepared','key_requested','key_saved','setting_requested','verified'}):
            raise PreflightError('Journal de signature invalide.')
    if journal['state'] == 'key_requested':
        # The only copy of the secret is the create response. If it was not
        # persisted, no list/fetch can reconstruct it. Do not create another key.
        if not key_path.exists():
            raise PreflightError('Création de clé incertaine ; aucun nouvel envoi. Réconciliation manuelle requise.')
        key = validate_key(read_private(key_path))
        if key['id'] in journal['before']['SharedKeys']:
            raise PreflightError('Cette clé existait avant la préparation.')
        journal.update(state='key_saved', key_id=key['id'])
        save(journal, path, replace=True)
    if journal['state'] != 'setting_requested':
        preserved(journal, inventory)
    if journal['state'] == 'prepared' and action == 'apply':
        if key_path.exists() or key_path.is_symlink():
            raise PreflightError('Un fichier de clé existe déjà ; aucun remplacement.')
        journal['state'] = 'key_requested'
        save(journal, path, replace=True)
        response = provider.request('POST', '/SharedKeys', {'friendlyName': NAME})
        key = validate_key({field: response.get(field) for field in ('id','secret','friendlyName')})
        write_private(key, key_path)
        directory = os.open(key_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        journal.update(state='key_saved', key_id=key['id'])
        save(journal, path, replace=True)
        inventory = provider.inventory()
        preserved(journal, inventory)
    if journal['state'] in {'key_saved','setting_requested','verified'}:
        key = validate_key(read_private(key_path))
        if key['id'] != journal['key_id']:
            raise PreflightError('Clé privée différente du journal.')
        fetched = provider.request('GET', '/SharedKeys/' + key['id'])
        if fetched.get('id') != key['id'] or fetched.get('friendlyName') != NAME:
            raise PreflightError('Clé fournisseur différente du plan.')
    if journal['state'] == 'key_saved' and action == 'apply':
        journal['state'] = 'setting_requested'
        save(journal, path, replace=True)
        created = validate_setting(provider.request('POST', '/Settings', setting(journal['key_id'])), journal['key_id'])
        if created['id'] in journal['before']['Settings']:
            raise PreflightError('Ce paramétrage existait avant la préparation.')
        journal['setting_id'] = created['id']
        save(journal, path, replace=True)
        inventory = provider.inventory()
    if journal['state'] == 'setting_requested':
        matches = [row for key, row in inventory['Settings'].items()
                   if key not in journal['before']['Settings'] and row.get('friendlyName') == NAME]
        if len(matches) != 1:
            raise PreflightError('Création du paramétrage incertaine ; aucun nouvel envoi.')
        found = validate_setting(matches[0], journal['key_id'])
        if journal['setting_id'] not in (None, found['id']):
            raise PreflightError('Paramétrage fournisseur ambigu.')
        journal.update(state='verified', setting_id=found['id'])
        save(journal, path, replace=True)
    if journal['state'] == 'verified':
        preserved(journal, inventory)
        fetched = provider.request('GET', '/Settings/' + journal['setting_id'])
        validate_setting(fetched, journal['key_id'])
        if fetched['id'] != journal['setting_id']:
            raise PreflightError('Identité du paramétrage différente du journal.')
    return {'state': journal['state'], 'key_secret_saved': key_path.exists(), 'setting_id': journal['setting_id'],
            'existing_rules_unchanged': True, 'rule_applied': False, 'calling_enabled': False}


def assemble(config, journal, key, application):
    validate_key(key)
    application_journal(application, config)
    if (journal['state'] != 'verified' or journal['binding'] != binding(config) or journal['key_id'] != key['id']
            or application['state'] != 'verified'):
        raise PreflightError('Les ressources Voice ne sont pas vérifiées.')
    return {'version': 1, 'mode': 'controlled_test', **{key: config[key] for key in
            ('account_sid','api_key_sid','api_key_secret','public_origin','caller_number','approved_destination')},
            'twiml_app_sid': application['application_sid'], 'shared_key_id': key['id'], 'shared_key_secret': key['secret']}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Préparer une signature dédiée, sans règle active ni appel.')
    parser.add_argument('action', choices=['prepare','apply','check','profile'])
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise PreflightError('Exécutez cet outil dans le terminal root du serveur.')
        base = voice.load_base();plan = voice.validate_plan(read_private(voice.PLAN), base)
        config = voice.validate_credentials(read_private(voice.CREDENTIALS), plan, base)
        fd = os.open(JOURNAL.with_suffix('.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+') as lock:
            info = os.fstat(lock.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
                raise PreflightError('Verrou privé invalide.')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == 'profile':
                run('check', config)
                from twilio_voice_application import JOURNAL as APPLICATION
                value = assemble(config, read_private(JOURNAL), read_private(KEY), read_private(APPLICATION))
                if PROFILE.exists() or PROFILE.is_symlink():
                    if read_private(PROFILE) != value:
                        raise PreflightError('Un profil différent existe déjà ; aucun remplacement.')
                else:
                    write_private(value, PROFILE)
                print('Profil privé assemblé. Aucun appel activé.')
                return 0
            result = run(args.action, config)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except PreflightError as error:
        print(str(error), file=sys.stderr)
    except Exception:
        print('Préparation de signature interrompue. Aucun renvoi automatique ; aucun secret affiché.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

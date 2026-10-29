"""Create only a dedicated TwiML Application, with a durable no-retry journal.

No calls, tokens, phone-number updates or existing-application updates. Every
provider request is restricted to an explicit method/path allowlist. A response
timeout leaves an uncertain operation for read-only reconciliation, never a
second POST. This tool runs on the host, outside the application containers.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import ssl
import stat
import sys
from urllib.parse import urlencode
import urllib.request
from uuid import uuid4

import twilio_voice_preflight as voice
from staging_twilio_preflight import NoRedirect, PreflightError, private_parent, read_private, write_private

JOURNAL = voice.PLAN.with_name('twilio-voice-application.json')
LOCK = JOURNAL.with_suffix('.lock')
NAME = 'unlimited-talk-voice'
STATES = {'prepared', 'requested', 'created', 'verified'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def desired(config):
    return {'FriendlyName': NAME, 'VoiceUrl': config['public_origin'] + '/api/telephony/twilio/voice',
            'VoiceMethod': 'POST', 'StatusCallback': config['public_origin'] + '/api/telephony/twilio/parent-status',
            'StatusCallbackMethod': 'POST', 'VoiceCallerIdLookup': 'false',
            'PublicApplicationConnectEnabled': 'false'}


class Provider:
    def __init__(self, config, send=None):
        self.config = config
        self.base = 'https://api.twilio.com/2010-04-01/Accounts/' + config['account_sid']
        self.send = send

    def request(self, method, path, fields=None):
        allowed = ((method == 'GET' and path in ('/Applications.json?PageSize=1000', '/IncomingPhoneNumbers.json?PageSize=1000'))
                   or (method == 'GET' and re.fullmatch(r'/Applications/AP[0-9a-fA-F]{32}\.json', path))
                   or (method == 'POST' and path == '/Applications.json' and fields == desired(self.config)))
        if not allowed or (method == 'GET' and fields is not None):
            raise PreflightError('Opération fournisseur refusée.')
        token = base64.b64encode((self.config['api_key_sid'] + ':' + self.config['api_key_secret']).encode()).decode()
        headers = {'Authorization': 'Basic ' + token, 'Accept': 'application/json',
                   'User-Agent': 'Unlimited-Talks-application-setup/1'}
        data = None if fields is None else urlencode(fields).encode()
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        request = urllib.request.Request(self.base + path, headers=headers, data=data, method=method)
        if self.send is not None:
            return self.send(request)
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(request, timeout=15) as response:
            if response.status != (201 if method == 'POST' else 200):
                raise PreflightError('Réponse fournisseur inattendue.')
            raw = response.read(1048577)
        if len(raw) > 1048576:
            raise PreflightError('Réponse fournisseur trop volumineuse.')
        return json.loads(raw)

    def inventory(self):
        result = {}
        for resource, field, prefix in [('Applications', 'applications', 'AP'),
                                        ('IncomingPhoneNumbers', 'incoming_phone_numbers', 'PN')]:
            data = self.request('GET', '/' + resource + '.json?PageSize=1000')
            if (not isinstance(data, dict) or data.get('next_page_uri')
                    or not isinstance(data.get(field), list) or len(data[field]) > 1000):
                raise PreflightError('Inventaire fournisseur incomplet ; aucune création permise.')
            rows = {}
            for row in data[field]:
                if (not isinstance(row, dict) or row.get('account_sid') != self.config['account_sid']
                        or not isinstance(row.get('sid'), str) or not re.fullmatch(prefix + '[0-9a-fA-F]{32}', row['sid'])
                        or row['sid'] in rows):
                    raise PreflightError('Identité de ressource fournisseur invalide.')
                rows[row['sid']] = row
            result[resource] = rows
        number = result['IncomingPhoneNumbers'].get(self.config['phone_number_sid'], {})
        if (number.get('phone_number') != self.config['caller_number']
                or not isinstance(number.get('capabilities'), dict) or number['capabilities'].get('voice') is not True):
            raise PreflightError('Le numéro de test ne correspond pas au plan Voice.')
        return result


def hashes(rows):
    # Preserve every provider property, including previously unknown ones. Dates
    # are informational; resource settings, ownership and membership are compared.
    return {sid: digest({k: v for k, v in row.items() if k not in {'date_created', 'date_updated'}})
            for sid, row in rows.items()}


def binding(config):
    return digest({key: config[key] for key in ('account_sid', 'api_key_sid', 'phone_number_sid',
                                               'caller_number', 'approved_destination', 'public_origin')})


def validate_journal(journal, config):
    fields = {'version', 'binding', 'state', 'before_applications', 'before_numbers', 'application_sid'}
    if (not isinstance(journal, dict) or set(journal) != fields or type(journal['version']) is not int
            or journal['version'] != 1 or journal['binding'] != binding(config) or journal['state'] not in STATES):
        raise PreflightError('Journal TwiML invalide ou différent du plan courant.')
    for field, prefix in [('before_applications', 'AP'), ('before_numbers', 'PN')]:
        values = journal[field]
        if not isinstance(values, dict) or any(not re.fullmatch(prefix + '[0-9a-fA-F]{32}', key)
                                              or not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
                                              for key, value in values.items()):
            raise PreflightError('Empreintes fournisseur invalides.')
    sid = journal['application_sid']
    if ((journal['state'] in {'prepared', 'requested'} and sid is not None)
            or (journal['state'] in {'created', 'verified'} and
                (not isinstance(sid, str) or not re.fullmatch('AP[0-9a-fA-F]{32}', sid)))
            or sid in journal['before_applications']):
        raise PreflightError('Identité de la nouvelle application invalide.')
    return journal


def save(journal, path, replace=False):
    if len(json.dumps(journal).encode()) + 1 > 8192:
        raise PreflightError('Journal trop volumineux ; aucune création permise.')
    if not replace:
        write_private(journal, path)
    else:
        read_private(path)  # Reject links, wrong ownership and permissive modes.
        temporary = path.with_name(path.name + '.' + uuid4().hex)
        write_private(journal, temporary)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def unchanged(journal, inventory, exclude=None):
    apps = {sid: row for sid, row in inventory['Applications'].items() if sid != exclude}
    if hashes(apps) != journal['before_applications'] or hashes(inventory['IncomingPhoneNumbers']) != journal['before_numbers']:
        raise PreflightError('Les ressources existantes ont changé ; examen requis avant toute suite.')


def validate_application(row, config, sid):
    expected = {'account_sid': config['account_sid'], 'sid': sid, 'friendly_name': NAME,
                'voice_url': desired(config)['VoiceUrl'], 'voice_method': 'POST',
                'status_callback': desired(config)['StatusCallback'], 'status_callback_method': 'POST',
                'voice_caller_id_lookup': False, 'public_application_connect_enabled': False}
    if (not isinstance(row, dict) or any(row.get(key) != value or type(row.get(key)) is not type(value)
                                        for key, value in expected.items())
            or any(row.get(key) not in ('', None) for key in
                   ('voice_fallback_url', 'sms_url', 'sms_fallback_url', 'sms_status_callback', 'message_status_callback'))):
        raise PreflightError('La nouvelle application ne correspond pas à la configuration prévue.')


def run(action, config, path=JOURNAL, provider=None):
    provider = Provider(config) if provider is None else provider
    inventory = provider.inventory()
    if action == 'prepare' and not (path.exists() or path.is_symlink()):
        if any(row.get('friendly_name') == NAME for row in inventory['Applications'].values()):
            raise PreflightError('Une application porte déjà ce nom ; aucun rattachement ni remplacement automatique.')
        journal = {'version': 1, 'binding': binding(config), 'state': 'prepared',
                   'before_applications': hashes(inventory['Applications']),
                   'before_numbers': hashes(inventory['IncomingPhoneNumbers']), 'application_sid': None}
        save(journal, path)
    else:
        journal = validate_journal(read_private(path), config)
    if journal['state'] == 'prepared':
        unchanged(journal, inventory)
        if action == 'apply':
            journal['state'] = 'requested'
            save(journal, path, replace=True)  # Durable BEFORE the only permitted POST.
            created = provider.request('POST', '/Applications.json', desired(config))
            if (not isinstance(created, dict) or created.get('account_sid') != config['account_sid']
                    or not isinstance(created.get('sid'), str) or not re.fullmatch('AP[0-9a-fA-F]{32}', created['sid'])
                    or created['sid'] in journal['before_applications']):
                raise PreflightError('Résultat de création incertain ; rapprochement en lecture seule requis.')
            journal.update(state='created', application_sid=created['sid'])
            save(journal, path, replace=True)
            inventory = provider.inventory()
    if journal['state'] == 'requested':
        candidates = [row for sid, row in inventory['Applications'].items()
                      if sid not in journal['before_applications'] and row.get('friendly_name') == NAME]
        if len(candidates) != 1:
            raise PreflightError('Création incertaine. Aucun nouvel envoi ; vérification manuelle requise.')
        validate_application(candidates[0], config, candidates[0]['sid'])
        unchanged(journal, inventory, exclude=candidates[0]['sid'])
        journal.update(state='created', application_sid=candidates[0]['sid'])
        save(journal, path, replace=True)
    if journal['state'] in {'created', 'verified'}:
        sid = journal['application_sid']
        fetched = provider.request('GET', '/Applications/' + sid + '.json')
        validate_application(fetched, config, sid)
        if inventory['Applications'].get(sid) != fetched:
            # A list and fetch may differ in timestamps only; compare settings.
            if hashes({sid: inventory['Applications'].get(sid, {})}) != hashes({sid: fetched}):
                raise PreflightError('Configuration fournisseur incohérente entre liste et lecture.')
        unchanged(journal, inventory, exclude=sid)
        if journal['state'] != 'verified':
            journal['state'] = 'verified'
            save(journal, path, replace=True)
    return {'state': journal['state'], 'application_sid': journal['application_sid'],
            'existing_applications_unchanged': True, 'phone_numbers_unchanged': True,
            'public_webhooks_ready': False, 'calling_enabled': False, 'live_call_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Préparer et créer une application TwiML distincte, sans appel.')
    parser.add_argument('action', choices=['prepare', 'apply', 'check'])
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise PreflightError('Exécutez cet outil dans le terminal root du serveur.')
        base = voice.load_base()
        plan = voice.validate_plan(read_private(voice.PLAN), base)
        config = voice.validate_credentials(read_private(voice.CREDENTIALS), plan, base)
        private_parent(LOCK)
        fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, 'r+') as lock:
            info = os.fstat(lock.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
                raise PreflightError('Verrou privé invalide.')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = run(args.action, config)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except PreflightError as error:
        print(str(error), file=sys.stderr)
    except Exception:
        print('Opération interrompue. Aucun renvoi automatique ; consultez le journal privé avec check. Aucun secret affiché.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

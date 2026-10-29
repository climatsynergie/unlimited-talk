"""Private Voice SDK credential preparation; no provider writes or calls.

Separate from the legacy application's credentials and from the SIP experiment.
The number read verifies REST authentication only, not the key's type, SDK token
acceptance, account capacity, browser audio or permission to originate a call.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import warnings

from staging_twilio_preflight import (
    CONFIG as READ_ONLY_CONFIG, PreflightError, check as check_number,
    load as load_base, private_parent, read_private, write_private,
)

PLAN = READ_ONLY_CONFIG.with_name('twilio-voice-plan.json')
CREDENTIALS = READ_ONLY_CONFIG.with_name('twilio-voice-credentials.json')
PUBLIC_ORIGIN = 'https://staging.unlimitedtalkapp.com'
PLAN_FIELDS = {'version', 'mode', 'region', 'account_sid', 'phone_number_sid',
               'caller_number', 'approved_destination', 'public_origin'}
KEY_FIELDS = {'requested_key_type', 'api_key_sid', 'api_key_secret'}


def validate_plan(plan, base):
    if (not isinstance(plan, dict) or set(plan) != PLAN_FIELDS
            or type(plan['version']) is not int or plan['version'] != 1
            or plan['mode'] != 'credentials_only' or plan['region'] != 'us1'
            or plan['public_origin'] != PUBLIC_ORIGIN):
        raise PreflightError('Plan Voice invalide ; les appels doivent rester désactivés.')
    for field in ('account_sid', 'phone_number_sid', 'caller_number'):
        if plan[field] != base[field]:
            raise PreflightError('Le plan Voice ne correspond pas au compte et au numéro vérifiés.')
    destination = plan['approved_destination']
    if (not isinstance(destination, str) or not re.fullmatch(r'\+[1-9][0-9]{8,14}', destination)
            or destination == plan['caller_number']):
        raise PreflightError('Destinataire de test invalide.')
    return plan


def prepare_plan(request, base):
    if not isinstance(request, dict) or set(request) != {'approved_destination', 'public_origin'}:
        raise PreflightError('Demande de préparation Voice invalide.')
    return validate_plan({'version': 1, 'mode': 'credentials_only', 'region': 'us1',
                          **{key: base[key] for key in ('account_sid', 'phone_number_sid', 'caller_number')},
                          **request}, base)


def validate_credentials(config, plan, base):
    validate_plan(plan, base)
    if not isinstance(config, dict) or set(config) != PLAN_FIELDS | KEY_FIELDS:
        raise PreflightError('Format des identifiants Voice invalide.')
    if any(config[field] != plan[field] for field in PLAN_FIELDS) or config['requested_key_type'] != 'standard':
        raise PreflightError('Les identifiants doivent correspondre au plan Voice contrôlé.')
    # Reuse the strict SID/secret validation and number binding without making a
    # network request. Never reuse the existing Restricted read-only credential.
    from staging_twilio_preflight import validate
    validate({**base, 'api_key_sid': config['api_key_sid'], 'api_key_secret': config['api_key_secret']})
    if config['api_key_sid'] == base['api_key_sid']:
        raise PreflightError('Créez une clé Standard distincte de la clé limitée existante.')
    return config


def collect(plan, base, prompt=getpass.getpass):
    validate_plan(plan, base)
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        key = prompt('SID de la nouvelle clé Standard US1 (SK…, invisible) : ').strip()
        secret = prompt('Secret de la nouvelle clé Standard (invisible) : ')
        confirmation = prompt('Confirmez ce secret : ')
    if secret != confirmation:
        raise PreflightError('Les secrets sont différents. Aucun enregistrement.')
    return validate_credentials({**plan, 'requested_key_type': 'standard',
                                 'api_key_sid': key, 'api_key_secret': secret}, plan, base)


def check(config, plan, base, send=None):
    validate_credentials(config, plan, base)
    projection = {**base, 'api_key_sid': config['api_key_sid'], 'api_key_secret': config['api_key_secret']}
    number = check_number(projection) if send is None else check_number(projection, send)
    return {**number, 'status': 'voice_credentials_read_verified',
            'approved_destination_last_four': plan['approved_destination'][-4:],
            'requested_key_type': 'standard', 'key_type_verified': False,
            'twiml_application_prepared': False, 'sdk_token_acceptance_verified': False,
            'calling_enabled': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Préparation privée de Voice, sans appel ni modification Twilio.')
    parser.add_argument('action', choices=['plan', 'store', 'check'])
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise PreflightError('Exécutez cet outil dans le terminal root du serveur.')
        base = load_base()
        if args.action == 'plan':
            raw = sys.stdin.buffer.read(2049)
            if len(raw) > 2048:
                raise PreflightError('Demande de préparation trop volumineuse.')
            plan = prepare_plan(json.loads(raw), base)
            write_private(plan, PLAN)
            print('Plan Voice privé enregistré. Les appels restent désactivés.')
            return 0
        plan = validate_plan(read_private(PLAN), base)
        if args.action == 'store':
            if CREDENTIALS.exists() or CREDENTIALS.is_symlink():
                raise PreflightError('Des identifiants Voice existent déjà. Aucun remplacement.')
            private_parent(CREDENTIALS)
            write_private(collect(plan, base), CREDENTIALS)
            print('Clé Voice enregistrée dans un fichier privé. La connexion reste à vérifier ; aucun appel activé.')
            return 0
        result = check(read_private(CREDENTIALS), plan, base)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['voice_capability'] else 1
    except PreflightError as error:
        print(str(error), file=sys.stderr)
    except FileNotFoundError:
        print('Plan ou identifiants Voice absents. La préparation doit être complétée.', file=sys.stderr)
    except FileExistsError:
        print('Un fichier existe déjà. Aucun remplacement.', file=sys.stderr)
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print('Saisie interrompue. Utilisez un terminal interactif ; aucun secret affiché.', file=sys.stderr)
    except Exception:
        print('Préparation interrompue. Vérifiez la saisie, les permissions et la connexion HTTPS ; aucun secret affiché.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

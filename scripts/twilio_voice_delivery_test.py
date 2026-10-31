"""Deliver one provider-signed, no-business-effect probe; never send a call/SMS."""
import base64
from datetime import datetime, timezone
import json
import ssl
import sys
import urllib.request
import twilio_voice_preflight as voice
import twilio_voice_signing as signing
from staging_twilio_preflight import NoRedirect, PreflightError, read_private, write_private


def delivery_code(value):
    # Keep interpretation explicit; an API 200 does not prove webhook delivery.
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, dict):
        for key in ('statusCode', 'status', 'code'):
            if key in value and type(value[key]) is int:
                return value[key]
    return None


def run():
    import os
    if os.geteuid() != 0:
        raise PreflightError('Exécutez cet outil en root.')
    with urllib.request.urlopen('http://127.0.0.1:8110/health/ready', timeout=8) as response:
        health = json.load(response)
    if (health.get('status') != 'ready' or health.get('communications') != 'webhooks_only'
            or health.get('calling_enabled') is not False):
        raise PreflightError('La réception signée sans appels doit être saine.')
    base = voice.load_base()
    plan = voice.validate_plan(read_private(voice.PLAN), base)
    config = voice.validate_credentials(read_private(voice.CREDENTIALS), plan, base)
    journal = read_private(signing.JOURNAL)
    key = signing.validate_key(read_private(signing.KEY))
    # No signing mutations or Rule adoption. Verify the immutable Setting and key.
    provider = signing.Provider(config)
    setting = signing.validate_setting(provider.request('GET', '/Settings/' + journal['setting_id']), key['id'])
    if (journal['state'] != 'verified' or journal['binding'] != signing.binding(config)
            or setting['id'] != journal['setting_id'] or key['id'] != journal['key_id']):
        raise PreflightError('Ressources de signature non vérifiées.')
    target = config['public_origin'] + '/api/telephony/twilio/probe'
    if target != 'https://staging.unlimitedtalkapp.com/api/telephony/twilio/probe':
        raise PreflightError('URL de contrôle refusée.')
    body = {'url': target, 'settingId': journal['setting_id'], 'method': 'POST'}
    auth = base64.b64encode((config['api_key_sid'] + ':' + config['api_key_secret']).encode()).decode()
    request = urllib.request.Request('https://webhooks.twilio.com/v1/Webhooks/Tests',
        method='POST', data=json.dumps(body).encode(), headers={'Authorization':'Basic '+auth,
        'Content-Type':'application/json', 'Accept':'application/json'})
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request, timeout=25) as response:
        if response.status != 200:
            raise PreflightError('Réponse inattendue du test de livraison.')
        raw = response.read(65537)
    if len(raw) > 65536:
        raise PreflightError('Réponse du test trop volumineuse.')
    result = json.loads(raw)
    name = 'voice-delivery-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json'
    path = signing.JOURNAL.with_name(name)
    # Provider output stays private. It may contain delivery/request metadata.
    write_private(result, path)
    data = result.get('result', {}) if isinstance(result, dict) else {}
    code = delivery_code(data.get('response'))
    verified = result.get('url') == target and data.get('outcome') == 'DELIVERED' and code == 204
    report = {'delivery_verified': verified, 'outcome': data.get('outcome')
        if data.get('outcome') in {'DELIVERED','FAILED'} else 'unknown', 'http_status': code,
        'receipt': str(path), 'calling_enabled': False}
    print(json.dumps(report))
    if not verified:
        raise PreflightError('Livraison non vérifiée ; consultez le résultat privé. Ce test ne modifie aucune Rule.')


if __name__ == '__main__':
    try:
        run()
    except PreflightError as error:
        print(str(error), file=sys.stderr);raise SystemExit(1)
    except Exception:
        print('Test interrompu ; aucun secret affiché.', file=sys.stderr);raise SystemExit(1)

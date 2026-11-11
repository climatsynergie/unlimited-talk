"""Prove narrowly authorized incoming routes without rebasing the Voice journal.

All reads are local, bounded, private-file reads. Resource digests preserve every
provider field except the two informational timestamps, matching the historical
Voice journal. Legacy normalized snapshots are accepted only when reconstructing
one of at most 256 exact historical resource digests. No field is ignored.
"""
import hashlib
from itertools import product
import json
import re
from uuid import UUID

from staging_twilio_preflight import PreflightError, read_private

FIELDS = {'voice_url': 'VoiceUrl', 'voice_method': 'VoiceMethod', 'voice_application_sid': 'VoiceApplicationSid',
          'voice_fallback_url': 'VoiceFallbackUrl', 'voice_fallback_method': 'VoiceFallbackMethod',
          'status_callback': 'StatusCallback', 'status_callback_method': 'StatusCallbackMethod', 'trunk_sid': 'TrunkSid'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def resource(number):
    return {key: value for key, value in number.items() if key not in {'date_created', 'date_updated'}}


def routes(number):
    result = {key: number.get(key) for key in FIELDS}
    if any(value is not None and (not isinstance(value, str) or len(value) > 2048)
           for value in result.values()):
        raise ValueError('Invalid provider route')
    return {key: value or '' for key, value in result.items()}


def desired(origin):
    if not isinstance(origin, str) or not re.fullmatch(r'https://[a-z0-9.-]+', origin):
        raise ValueError('Canonical HTTPS origin required')
    return dict(voice_url=origin+'/api/telephony/twilio/incoming', voice_method='POST', voice_application_sid='',
                voice_fallback_url='', voice_fallback_method='POST',
                status_callback=origin+'/api/telephony/twilio/incoming-parent-status',
                status_callback_method='POST', trunk_sid='')


def validate_plan(plan, path, config=None):
    if not isinstance(plan, dict) or type(plan.get('version')) is not int or plan['version'] not in (1, 2):
        raise ValueError('Invalid incoming route plan version')
    fields = {'version', 'binding', 'previous', 'desired'}
    if plan['version'] == 2:
        fields |= {'before_resource', 'before_resource_digest'}
    if set(plan) != fields:
        raise ValueError('Invalid incoming route plan fields')
    binding = plan['binding']
    if not isinstance(binding, dict) or set(binding) != {'queue', 'phone', 'version', 'account', 'pn', 'origin'}:
        raise ValueError('Invalid incoming route binding')
    queue = binding['queue']
    if (not isinstance(queue, str) or str(UUID(queue)) != queue
            or path.name != 'incoming-line-'+queue+'.json'
            or type(binding['version']) is not int or binding['version'] < 0):
        raise ValueError('Incoming queue identity mismatch')
    for key, expression in [('account', 'AC[0-9a-fA-F]{32}'), ('pn', 'PN[0-9a-fA-F]{32}'),
                            ('phone', r'\+[1-9][0-9]{8,14}')]:
        if not isinstance(binding[key], str) or not re.fullmatch(expression, binding[key]):
            raise ValueError('Invalid incoming resource identity')
    if config and (binding['account'] != config['account_sid'] or binding['origin'] != config['public_origin']):
        raise ValueError('Incoming route differs from Voice account or origin')
    if plan['desired'] != desired(binding['origin']):
        raise ValueError('Incoming route is not the canonical application route')
    previous = plan['previous']
    if (not isinstance(previous, dict) or set(previous) != set(FIELDS)
            or any(not isinstance(value, str) or len(value) > 2048 for value in previous.values())):
        raise ValueError('Invalid previous incoming route')
    if plan['version'] == 2:
        before = plan['before_resource']
        if not isinstance(before, dict) or resource(before) != before:
            raise ValueError('Invalid before-resource snapshot')
        validate_number(before, binding)
        if routes(before) != previous or digest(before) != plan['before_resource_digest']:
            raise ValueError('Before-resource digest or route mismatch')
    return plan


def validate_number(number, binding):
    if (not isinstance(number, dict) or number.get('account_sid') != binding['account']
            or number.get('sid') != binding['pn'] or number.get('phone_number') != binding['phone']
            or not isinstance(number.get('capabilities'), dict) or number['capabilities'].get('voice') is not True):
        raise ValueError('Incoming provider number mismatch')


def original_resource(number, plan):
    """Restore only the eight route fields, preserving all other provider fields."""
    original = {key: value for key, value in resource(number).items() if key not in FIELDS}
    original.update({key: value for key, value in plan['before_resource'].items() if key in FIELDS})
    return original


def confirmed_receipt(plan, number, action):
    if plan['version'] != 2 or action not in {'connect', 'restore'}:
        raise ValueError('Full-resource receipt requires a v2 plan')
    validate_number(number, plan['binding'])
    target = plan['desired'] if action == 'connect' else plan['previous']
    if routes(number) != target or original_resource(number, plan) != plan['before_resource']:
        raise ValueError('Confirmed route changed unrelated provider fields')
    return dict(version=1, plan_digest=digest(plan), action=action,
                before_resource_digest=plan['before_resource_digest'], after_resource_digest=digest(resource(number)))


def prove_number(number, original_digest, plan, path):
    validate_number(number, plan['binding'])
    if plan['version'] == 2:
        receipt = read_private(path.with_suffix('.receipt.json'))
        fields = {'version', 'plan_digest', 'action', 'before_resource_digest', 'after_resource_digest'}
        if (not isinstance(receipt, dict) or set(receipt) != fields
                or type(receipt['version']) is not int or receipt['version'] != 1
                or receipt['action'] not in {'connect', 'restore'}):
            raise ValueError('Invalid incoming confirmation receipt')
        if (plan['before_resource_digest'] != original_digest
                or receipt != confirmed_receipt(plan, number, receipt['action'])):
            raise ValueError('Incoming route receipt mismatch')
        return
    if routes(number) not in (plan['desired'], plan['previous']):
        raise ValueError('Incoming route is incomplete or changed')
    # Legacy snapshots normalized None to ''. Try only these exact two original
    # representations for empty route values. Missing keys, other falsy values,
    # unknown fields, SMS settings and ownership are never normalized or dropped.
    empty = [key for key, value in plan['previous'].items() if value == '']
    original = dict(resource(number), **plan['previous'])
    for values in product(('', None), repeat=len(empty)):
        original.update(zip(empty, values))
        if digest(original) == original_digest:
            return
    raise ValueError('Legacy incoming snapshot cannot reconstruct historical resource')


def verify_authorized_changes(before_hashes, numbers, root, config):
    """Return the authorized changed number count, otherwise fail closed."""
    if set(before_hashes) != set(numbers):
        raise PreflightError('La liste des numéros Twilio a changé ; examen requis.')
    changed = {sid for sid, number in numbers.items() if digest(resource(number)) != before_hashes[sid]}
    if not changed:
        return 0
    try:
        paths = [path for path in root.glob('incoming-line-*.json') if not path.name.endswith('.receipt.json')]
        if len(paths) > 1000:
            raise ValueError('Too many incoming route plans')
        plans = {}
        for path in paths:
            plan = validate_plan(read_private(path), path, config)
            sid = plan['binding']['pn']
            if sid in plans:
                raise ValueError('Ambiguous incoming plans for one number')
            plans[sid] = (plan, path)
        for sid in changed:
            if sid not in plans:
                raise ValueError('Changed number has no preserved incoming plan')
            plan, path = plans[sid]
            prove_number(numbers[sid], before_hashes[sid], plan, path)
    except (ValueError, TypeError, KeyError, OSError) as error:
        raise PreflightError('Modification des numéros non prouvée par le plan entrant ; examen requis.') from error
    return len(changed)

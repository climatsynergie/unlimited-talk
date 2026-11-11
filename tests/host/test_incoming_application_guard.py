"""Synthetic provider regressions: authorized ingress must not disable egress guards."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_twilio_voice_application import ProviderFixture, module as application
import connect_incoming_line as incoming
import control_voice_test as controls


class IncomingApplicationGuardTests(ProviderFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.tmp.name) / 'routes'
        self.root.mkdir(mode=0o700)
        self.root_patch = patch.object(application, 'INCOMING_ROOT', self.root, create=True)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.pn = self.config['phone_number_sid']
        self.queue = '00000000-0000-0000-0000-000000000001'
        self.plan_path = self.root / ('incoming-line-' + self.queue + '.json')
        self.numbers[self.pn].update({key: None for key in incoming.FIELDS})
        self.other_pn = 'PN'+'8'*32
        self.numbers[self.other_pn] = dict(account_sid=self.config['account_sid'], sid=self.other_pn,
                                         phone_number='+14165550198', capabilities={'voice': True},
                                         **{key: None for key in incoming.FIELDS})
        self.numbers[self.pn].update(voice_url='https://legacy.invalid/voice', voice_method='POST',
                                     voice_fallback_method='POST', status_callback_method='POST',
                                     extra_future_setting={'must': 'remain identical'})
        self.original = copy.deepcopy(self.numbers[self.pn])
        self.run_action('prepare')
        self.run_action('apply')
        self.initial_posts = len(self.posts())
        self.binding = dict(queue=self.queue, phone=self.config['caller_number'], version=3,
                            account=self.config['account_sid'], pn=self.pn, origin=self.config['public_origin'])
        self.plan = dict(version=1, binding=self.binding, previous=incoming.routes(self.original),
                         desired=incoming.desired(self.config['public_origin']))

    def save(self, value=None, path=None):
        selected = path or self.plan_path
        selected.write_text(json.dumps(self.plan if value is None else value))
        selected.chmod(0o600)

    def connect(self):
        self.numbers[self.pn].update(self.plan['desired'])

    def reject(self):
        with self.assertRaises((application.PreflightError, ValueError, OSError)):
            self.run_action('check')
        self.assertEqual(len(self.posts()), self.initial_posts)

    def test_authorized_legacy_selected_route_preserves_verified_outbound_application(self):
        self.save(); self.connect()
        before = self.path.read_bytes()
        result = self.run_action('check')
        self.assertEqual(result['state'], 'verified')
        self.assertIs(result['phone_numbers_unchanged'], False)
        self.assertIs(result['phone_numbers_verified'], True)
        self.assertEqual(result['authorized_incoming_routes'], 1)
        self.assertEqual(self.path.read_bytes(), before, 'immutable application baseline must never be rewritten')
        self.assertEqual(len(self.posts()), self.initial_posts)

    def test_legacy_normalized_empties_require_exact_original_digest_reconstruction(self):
        self.save(); self.connect()
        self.numbers[self.pn]['voice_application_sid'] = None
        self.numbers[self.pn]['trunk_sid'] = None
        self.assertEqual(self.run_action('check')['state'], 'verified')

    def test_unrelated_or_unknown_properties_remain_protected(self):
        self.save(); self.connect()
        for key, value in [('extra_future_setting', {'must': 'not drift'}), ('sms_url', 'https://other.invalid'),
                           ('account_sid', 'AC' + '9' * 32), ('phone_number', '+14165550199'),
                           ('capabilities', {'voice': True, 'sms': False})]:
            original = copy.deepcopy(self.numbers[self.pn])
            self.numbers[self.pn][key] = value
            with self.subTest(field=key): self.reject()
            self.numbers[self.pn] = original

    def test_partial_route_and_unrelated_resource_changes_remain_blocked(self):
        self.save(); self.connect()
        self.numbers[self.other_pn]['sms_url'] = 'https://foreign.invalid'
        self.reject(); del self.numbers[self.other_pn]['sms_url']
        self.numbers[self.pn]['status_callback'] = 'https://foreign.invalid'
        self.reject(); self.connect()
        self.apps[self.old_sid]['extra_future_setting'] = 'changed'
        self.reject(); self.apps[self.old_sid]['extra_future_setting'] = 'preserve-me'
        other = 'PN' + '9' * 32
        self.numbers[other] = dict(self.original, sid=other, phone_number='+14165550199')
        self.reject(); del self.numbers[other]
        del self.numbers[self.pn]; self.reject()

    def test_unproved_or_ambiguous_legacy_changes_are_rejected(self):
        self.connect(); self.reject()
        for mutate in [lambda p: p['binding'].update(origin='https://other.invalid'),
                       lambda p: p['binding'].update(pn='PN'+'9'*32),
                       lambda p: p['binding'].update(phone='+14165550199'),
                       lambda p: p['binding'].update(account='AC'+'9'*32),
                       lambda p: p['previous'].update(voice_url='https://invented.invalid'),
                       lambda p: p['previous'].update(unknown='unchecked'),
                       lambda p: p.update(version=True), lambda p: p.update(unexpected=True),
                       lambda p: p['binding'].update(version=-1)]:
            plan = copy.deepcopy(self.plan); mutate(plan); self.save(plan)
            with self.subTest(plan=plan): self.reject()
        self.save()
        other = self.root / 'incoming-line-00000000-0000-0000-0000-000000000002.json'
        duplicate = copy.deepcopy(self.plan); duplicate['binding']['queue'] = other.stem.removeprefix('incoming-line-')
        self.save(duplicate, other); self.reject()

    def test_private_plan_permissions_links_and_malformed_payload_are_rejected(self):
        self.save(); self.connect(); self.plan_path.chmod(0o640); self.reject()
        self.plan_path.chmod(0o600)
        real = self.root / 'real.json'; self.plan_path.rename(real); self.plan_path.symlink_to(real)
        self.reject(); self.plan_path.unlink(); self.plan_path.write_text('{"version":'); self.plan_path.chmod(0o600)
        self.reject()

    def test_v2_requires_confirmed_receipt_matching_exact_full_resource_digests(self):
        self.plan['binding']['version'] = 0
        self.plan.update(version=2, before_resource={k:v for k,v in self.original.items()
                                                   if k not in {'date_created', 'date_updated'}})
        self.plan['before_resource_digest'] = application.hashes({self.pn:self.original})[self.pn]
        self.save(); self.connect(); self.reject()
        receipt = dict(version=1, plan_digest=application.digest(self.plan), action='connect',
                       before_resource_digest=self.plan['before_resource_digest'],
                       after_resource_digest=application.hashes(self.numbers)[self.pn])
        receipt_path = self.plan_path.with_suffix('.receipt.json')
        self.save(receipt, receipt_path)
        self.assertEqual(self.run_action('check')['state'], 'verified')
        correct = copy.deepcopy(receipt)
        for change in [{'after_resource_digest':'0'*64}, {'before_resource_digest':'0'*64},
                       {'plan_digest':'0'*64}, {'version':True}, {'action':'unknown'}, {'extra':'unknown'}]:
            self.save(correct | change, receipt_path); self.reject()
        self.save(correct, receipt_path)
        receipt_path.chmod(0o640); self.reject(); receipt_path.chmod(0o600)
        self.apps[self.new_sid]['voice_url'] = 'https://unapproved.invalid'
        self.reject(); self.apps[self.new_sid]['voice_url'] = application.desired(self.config)['VoiceUrl']
        self.numbers[self.pn].update(self.plan['previous'])
        self.reject()  # A stale connect receipt cannot authorize a restore.
        receipt = dict(correct, action='restore', after_resource_digest=application.hashes(self.numbers)[self.pn])
        self.save(receipt, receipt_path)
        self.assertEqual(self.run_action('check')['state'], 'verified')
        self.numbers[self.pn]['sms_url'] = 'https://foreign.invalid'
        self.reject()

    def test_legacy_restore_with_normalized_nulls_proves_original_full_digest(self):
        self.save(); self.connect()
        self.assertEqual(self.run_action('check')['state'], 'verified')
        self.numbers[self.pn].update(self.plan['previous'])
        self.assertNotEqual(application.hashes(self.numbers)[self.pn],
                            application.hashes({self.pn:self.original})[self.pn])
        self.assertEqual(self.run_action('check')['state'], 'verified')
        self.numbers[self.pn]['voice_url'] = 'https://unapproved.invalid'
        self.reject()

    def test_all_eight_legacy_nulls_use_bounded_exact_reconstruction(self):
        self.original.update({key:None for key in incoming.FIELDS})
        journal = application.read_private(self.path)
        journal['before_numbers'][self.pn] = application.hashes({self.pn:self.original})[self.pn]
        self.path.write_text(json.dumps(journal)); self.path.chmod(0o600)
        self.plan['previous'] = incoming.routes(self.original)
        self.save(); self.connect()
        self.assertEqual(self.run_action('check')['state'], 'verified')

    def test_two_authorized_numbers_require_two_unambiguous_independent_proofs(self):
        self.save(); self.connect()
        queue = '00000000-0000-0000-0000-000000000002'
        other_plan = copy.deepcopy(self.plan)
        other_plan['binding'].update(queue=queue, pn=self.other_pn, phone=self.numbers[self.other_pn]['phone_number'])
        other_plan['previous'] = incoming.routes(self.numbers[self.other_pn])
        self.save(other_plan, self.root/('incoming-line-'+queue+'.json'))
        self.numbers[self.other_pn].update(other_plan['desired'])
        result = self.run_action('check')
        self.assertEqual(result['authorized_incoming_routes'],2)
        self.assertIs(result['phone_numbers_unchanged'],False)

    def test_legacy_authorization_cannot_relax_application_creation_guard(self):
        journal = application.read_private(self.path)
        journal.update(state='prepared', application_sid=None)
        self.path.write_text(json.dumps(journal)); self.path.chmod(0o600)
        del self.apps[self.new_sid]
        self.save(); self.connect()
        with self.assertRaises(application.PreflightError): self.run_action('apply')
        self.assertEqual(len(self.posts()), self.initial_posts)

class IncomingReceiptOperatorTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.queue = '00000000-0000-0000-0000-000000000003'
        self.pn = 'PN'+'b'*32
        self.profile = dict(account_sid='AC'+'a'*32, api_key_sid='SK'+'c'*32,
                            api_key_secret='synthetic-only', public_origin='https://voice.example.invalid')
        self.original = dict(account_sid=self.profile['account_sid'], sid=self.pn, phone_number='+14165550101',
                             capabilities={'voice': True}, future_setting={'retain': True},
                             **{key: None for key in incoming.FIELDS})
        self.current = copy.deepcopy(self.original)
        self.requests = []; self.events = []; self.drift_after_post = False
        self.path = self.root / ('incoming-line-'+self.queue+'.json')
        (self.root/'voice-runtime.json').write_text(json.dumps(self.profile))
        (self.root/'voice-runtime.json').chmod(0o600)
        self.patches = [patch.object(incoming,'ROOT',self.root), patch.object(incoming,'runtime',return_value=['synthetic']),
                        patch.object(incoming,'os',SimpleNamespace(geteuid=lambda:0)),
                        patch.object(incoming,'protected',side_effect=lambda path: application.read_private(path)),
                        patch.object(controls,'protected',side_effect=lambda path: application.read_private(path)),
                        patch.object(incoming,'run',return_value=json.dumps({'version':0,'phone':'+14165550101'})),
                        patch.object(incoming,'database',side_effect=self.db),
                        patch.object(incoming,'Provider',return_value=self)]
        for item in self.patches: item.start(); self.addCleanup(item.stop)

    def db(self, command, action, values):
        if action == 'active':
            self.assertTrue(self.path.with_suffix('.receipt.json').exists(), 'receipt durable before DB activation')
        self.events.append(action)

    def request(self, method, values=None):
        self.requests.append((method,copy.deepcopy(values)))
        if method == 'POST':
            self.current.update(values)
            if self.drift_after_post: self.current['future_setting'] = 'unrelated mutation'
            raise TimeoutError('synthetic lost provider acknowledgement')
        return copy.deepcopy(self.current)

    def operate(self, action):
        return incoming.operate(action, 'a'*40, self.queue, self.pn)

    def test_new_prepare_preserves_full_resource_without_any_provider_write(self):
        self.operate('prepare')
        plan = application.read_private(self.path)
        self.assertEqual(plan['version'],2)
        self.assertEqual(plan['binding']['version'],0, 'fresh queues start at version zero')
        self.assertEqual(plan['before_resource'],self.original)
        self.assertEqual(plan['before_resource_digest'],application.hashes({self.pn:self.original})[self.pn])
        self.assertEqual([method for method,_ in self.requests],['GET'])

    def test_oversized_resource_snapshot_fails_before_creating_an_unreadable_plan(self):
        self.current['future_setting'] = 'x'*8192
        with self.assertRaises(ValueError): self.operate('prepare')
        self.assertFalse(self.path.exists())
        self.assertEqual([method for method,_ in self.requests],['GET'])

    def test_confirmed_route_receipt_is_durable_and_retries_do_not_repost(self):
        self.operate('prepare'); self.operate('connect')
        receipt_path = self.path.with_suffix('.receipt.json')
        receipt = application.read_private(receipt_path)
        plan = application.read_private(self.path)
        self.assertEqual(receipt['plan_digest'],application.digest(plan))
        self.assertEqual(receipt['before_resource_digest'],application.hashes({self.pn:self.original})[self.pn])
        self.assertEqual(receipt['after_resource_digest'],application.hashes({self.pn:self.current})[self.pn])
        self.operate('connect')
        self.assertEqual(sum(method=='POST' for method,_ in self.requests),1)
        self.operate('restore')
        self.assertEqual(incoming.routes(self.current),incoming.routes(self.original))
        receipt = application.read_private(receipt_path)
        self.assertEqual(receipt['action'],'restore')
        import incoming_route_proof as proof
        proof.prove_number(self.current,plan['before_resource_digest'],plan,self.path)

    def test_unrelated_drift_before_or_during_write_cannot_obtain_confirmation_receipt(self):
        self.operate('prepare'); self.current['future_setting'] = 'unexpected'
        with self.assertRaises(ValueError): self.operate('connect')
        self.assertEqual(sum(method=='POST' for method,_ in self.requests),0)
        self.current = copy.deepcopy(self.original); self.drift_after_post = True
        with self.assertRaises(ValueError): self.operate('connect')
        self.assertFalse(self.path.with_suffix('.receipt.json').exists())
        self.assertNotIn('active',self.events)


if __name__ == '__main__':
    unittest.main()

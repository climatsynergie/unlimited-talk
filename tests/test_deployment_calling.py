"""Deployment orchestration preserves calling intent and refuses active calls."""
from contextlib import ExitStack
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('calling_deployer',
    Path(__file__).resolve().parents[1] / 'scripts/deploy_staging.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DeploymentCallingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = folder / 'config'
        self.base = folder / 'base'
        self.template = self.root / 'deployment-template'
        self.template.mkdir(parents=True)
        self.previous = self.base / 'releases' / ('git-' + 'a' * 40)
        self.previous.mkdir(parents=True)
        (self.base / 'current').symlink_to(self.previous)
        self.revision = 'b' * 40
        self.release = self.previous.parent / ('git-' + self.revision)
        self.image = module.REGISTRY_IMAGE + '@sha256:' + 'c' * 64
        self.request = dict(revision=self.revision, image=self.image,
                            registry_user='example-user', token='x' * 48)
        for name, value in (
                ('postgres-runtime.json', {'host': 'private.example.invalid'}),
                ('deployment-network.json', {'database_cidr': '10.0.0.0/24'}),
                ('identity-config.json', {'origin': 'https://app.example.invalid'})):
            (self.root / name).write_text(json.dumps(value))
        for name in ('compose.managed.yaml', 'nginx.conf', 'broker-start.sh'):
            (self.template / name).write_text('synthetic template')
        self.enabled = {self.previous: True, self.release: False}
        self.active = [0]
        self.events = []
        self.failure = None
        for name, value in (('ROOT', self.root), ('BASE', self.base), ('TEMPLATE', self.template)):
            self.stack.enter_context(patch.object(module, name, value))
        for name, function in (('github', self.github), ('run', self.command), ('compose', self.compose),
                               ('calling_state', self.state), ('calling_action', self.action),
                               ('check_health', self.health)):
            self.stack.enter_context(patch.object(module, name, side_effect=function))
        original_temporary = tempfile.TemporaryDirectory
        self.stack.enter_context(patch.object(module.tempfile, 'TemporaryDirectory',
            side_effect=lambda **kwargs: original_temporary(dir=folder)))

    def github(self, path, token):
        if path == 'commits/main':
            return {'sha': self.revision}
        return {'workflow_runs': [{'head_sha': self.revision,
            'head_repository': {'full_name': module.REPOSITORY},
            'conclusion': 'success', 'event': 'push'}]}

    def command(self, args, **kwargs):
        if args[:2] == ['gh', 'attestation']:
            self.events.append('provenance')
            if self.failure == 'provenance':
                raise RuntimeError('Unverified image')
        if args[:3] == ['docker', 'image', 'inspect']:
            return json.dumps({'org.opencontainers.image.revision': self.revision,
                'org.opencontainers.image.source': 'https://github.com/' + module.REPOSITORY,
                'io.unlimitedtalk.schema': '0010_dialer', 'io.unlimitedtalk.inbound-config': '1',
                'io.unlimitedtalk.voice-archive': '1', 'io.unlimitedtalk.voice-manual': '1',
                'io.unlimitedtalk.dialer-compatible': '1', 'io.unlimitedtalk.dialer': '1'})
        return ''

    def compose(self, release, *args, **kwargs):
        if args[0] == 'config':
            return json.dumps({'name': 'unlimited-talk-staging-managed', 'services': {
                name: {'image': self.image} for name in ('api', 'migrate', 'gateway', 'broker',
                    'worker', 'dispatcher', 'voice-reconciler', 'voice-archiver')}})
        if args[0] == 'exec':
            self.assertIn('SET TRANSACTION READ ONLY', kwargs['data'])
            self.events.append('idle')
            return str(self.active.pop(0) if len(self.active) > 1 else self.active[0])
        if args[0] == 'run':
            self.events.append('migrate')
            self.assertFalse(self.enabled[self.previous])
            if self.failure == 'migration':
                raise RuntimeError('Migration failed')
        return ''

    def state(self, release):
        if self.failure == 'unrecoverable' and 'migrate' in self.events:
            raise RuntimeError('Unhealthy runtime')
        return dict(status='ready', environment='staging', revision=release.name[4:],
            migration='0010_dialer', communications='manual' if self.enabled[release] else 'webhooks_only',
            calling_enabled=self.enabled[release])

    def action(self, action, revision):
        release = self.previous.parent / ('git-' + revision)
        self.events.append((action, revision))
        if action == 'enable' and self.failure == 'resume':
            raise RuntimeError('Calling verification failed')
        self.enabled[release] = action == 'enable'

    def health(self, revision=None):
        current = (self.base / 'current').resolve()
        if (self.failure in {'startup', 'unrecoverable'} and current == self.release
                or self.failure == 'unrecoverable' and 'migrate' in self.events):
            raise RuntimeError('Readiness failed')
        self.assertFalse(self.enabled[current])
        return self.state(current)

    def test_success_pauses_only_after_provenance_and_resumes_the_new_release(self):
        result = module.deploy(self.request)
        self.assertTrue(result['calling_enabled'])
        self.assertTrue(self.enabled[self.release])
        self.assertLess(self.events.index('provenance'), self.events.index(('disable', 'a' * 40)))
        self.assertLess(self.events.index(('disable', 'a' * 40)), self.events.index('migrate'))
        self.assertEqual(self.events[-1], ('enable', self.revision))

    def test_an_intentional_shutdown_is_not_automatically_armed(self):
        self.enabled[self.previous] = False
        result = module.deploy(self.request)
        self.assertFalse(result['calling_enabled'])
        self.assertFalse(any(isinstance(e, tuple) for e in self.events))

    def test_active_calls_refuse_deployment_without_disabling_them(self):
        self.active = [1]
        with self.assertRaises(module.ActiveCallsError):
            module.deploy(self.request)
        self.assertTrue(self.enabled[self.previous])
        self.assertNotIn('migrate', self.events)
        self.assertFalse(any(isinstance(e, tuple) for e in self.events))

    def test_a_racing_call_restores_the_old_mode_without_migration(self):
        self.active = [0, 1]
        with self.assertRaises(module.ActiveCallsError):
            module.deploy(self.request)
        self.assertTrue(self.enabled[self.previous])
        self.assertNotIn('migrate', self.events)
        self.assertEqual(self.events[-1], ('enable', 'a' * 40))

    def test_migration_and_readiness_failures_resume_the_healthy_previous_release(self):
        for failure in ('migration', 'startup'):
            with self.subTest(failure=failure):
                self.failure = failure
                self.events.clear()
                with self.assertRaises(RuntimeError):
                    module.deploy(self.request)
                self.assertEqual((self.base / 'current').resolve(), self.previous)
                self.assertTrue(self.enabled[self.previous])
                self.assertFalse(self.enabled[self.release])
                self.assertEqual(self.events[-1], ('enable', 'a' * 40))

    def test_unhealthy_rollback_and_failed_calling_verification_stay_closed(self):
        for failure in ('unrecoverable', 'resume'):
            with self.subTest(failure=failure):
                self.failure = failure
                self.events.clear()
                if (self.base / 'current').resolve() != self.previous:
                    module.switch_current(self.previous)
                self.enabled = {self.previous: True, self.release: False}
                with self.assertRaises(module.CallingResumeError):
                    module.deploy(self.request)
                self.assertFalse(self.enabled[self.previous])
                self.assertFalse(self.enabled[self.release])

    def test_provenance_failure_never_changes_calling(self):
        self.failure = 'provenance'
        with self.assertRaises(RuntimeError):
            module.deploy(self.request)
        self.assertTrue(self.enabled[self.previous])
        self.assertFalse(any(isinstance(e, tuple) for e in self.events))

    def test_real_state_reader_rejects_wrong_revision_or_incoherent_modes(self):
        self.stack.close()
        # A separate fixture avoids restoring any deployment state or making I/O.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            release = base / 'releases' / ('git-' + 'a' * 40)
            state = dict(status='ready', environment='staging', revision='a' * 40,
                         communications='manual', calling_enabled=True)
            for change in ({}, {'calling_enabled': False}, {'revision': 'b' * 40},
                           {'communications': 'controlled_test'}, {'status': 'unhealthy'}):
                with patch.object(module, 'BASE', base), patch.object(module.urllib.request,
                        'urlopen', return_value=io.StringIO(json.dumps(state | change))):
                    if change:
                        with self.assertRaises(RuntimeError):
                            module.calling_state(release)
                    else:
                        self.assertTrue(module.calling_state(release)['calling_enabled'])

    def test_long_schema_requires_compatible_previous_image_before_calling_changes(self):
        labels={'io.unlimitedtalk.schema':'0011_long_recordings'}
        current={'org.opencontainers.image.revision':'a'*40,
                 'org.opencontainers.image.source':'https://github.com/'+module.REPOSITORY}
        with patch.object(module,'compose',return_value='a'*64), patch.object(module,'run',return_value=json.dumps(current)):
            with self.assertRaises(ValueError):module.require_recording_compatibility(labels,self.previous)
        self.assertTrue(self.enabled[self.previous]);self.assertEqual(self.events,[])
        current['io.unlimitedtalk.schema11-compatible']='1'
        with patch.object(module,'compose',return_value='a'*64), patch.object(module,'run',return_value=json.dumps(current)):
            module.require_recording_compatibility(labels,self.previous)
        self.assertTrue(self.enabled[self.previous]);self.assertEqual(self.events,[])

    def test_existing_long_schema_requires_no_new_compatibility_transition(self):
        with patch.object(module,'calling_state',return_value={'migration':'0011_long_recordings'}), patch.object(module,'run') as run:
            module.require_recording_compatibility({'io.unlimitedtalk.schema':'0011_long_recordings'},self.previous)
            run.assert_not_called()

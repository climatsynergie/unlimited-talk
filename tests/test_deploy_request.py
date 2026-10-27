import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'scripts/deploy_staging.py'
spec = importlib.util.spec_from_file_location('deploy_staging', path)
deployer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)


class DeploymentRequestTests(unittest.TestCase):
    def setUp(self):
        self.request = {'revision': 'a' * 40,
                        'image': 'ghcr.io/climatsynergie/unlimited-talk-api@sha256:' + 'b' * 64,
                        'registry_user': 'example-user', 'token': 'x' * 48}

    def test_identity_migration_requires_a_compatible_rollback_target(self):
        labels={'io.unlimitedtalk.schema':'0002_identity'}
        for running in [
            {'migration':'0001_foundation','revision':'d6ffee3e4d6d3cb293b433f2ff47e1b3e1445b0a'},
            {'migration':'0002_identity','revision':'a'*40}]:
            with patch.object(deployer,'check_health',return_value=running):
                deployer.require_identity_rollback_target(labels)
        for running in [{}, {'migration':'0001_foundation','revision':'a'*40}, {'migration':'unexpected'}]:
            with patch.object(deployer,'check_health',return_value=running), self.assertRaises(ValueError):
                deployer.require_identity_rollback_target(labels)

    def test_expected_request(self):
        self.assertEqual(deployer.parse_request(json.dumps(self.request)), self.request)

    def test_refuses_mutable_tags_and_other_registries(self):
        for image in ('ghcr.io/climatsynergie/unlimited-talk-api:latest',
                      'other.example/image@sha256:' + 'b' * 64):
            with self.subTest(image=image), self.assertRaises(ValueError):
                deployer.parse_request(json.dumps({**self.request, 'image': image}))

    def test_refuses_command_injection_and_extra_fields(self):
        for changes in ({'revision': 'main;id'}, {'registry_user': 'x --password bad'},
                        {'shell': '/bin/sh'}, {'token': 'contains whitespace'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                deployer.parse_request(json.dumps({**self.request, **changes}))

    def test_refuses_oversized_input_and_nonstring_values(self):
        for raw in ('x' * 17000, json.dumps({**self.request, 'token': ['secret']})):
            with self.assertRaises(ValueError):
                deployer.parse_request(raw)

    def test_non_main_revision_never_reaches_registry_or_database(self):
        with patch.object(deployer, 'github', return_value={'sha': 'c' * 40}), patch.object(deployer, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'current main'):
                deployer.deploy(self.request)
            command.assert_not_called()

    def test_health_failure_restores_previous_release_without_database_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'config'
            base = root / 'base'
            template = config / 'deployment-template'
            template.mkdir(parents=True)
            (base / 'releases/previous').mkdir(parents=True)
            previous = base / 'releases/previous'
            (base / 'current').symlink_to(previous)
            (config / 'postgres-runtime.json').write_text(json.dumps({'host': 'private-db-example.d.db.ondigitalocean.com'}))
            (config / 'deployment-network.json').write_text(json.dumps({'database_cidr': '10.0.0.0/24'}))
            (config / 'identity-config.json').write_text(json.dumps({'origin':'https://staging.example.com'}))
            (template / 'compose.managed.yaml').write_text('fixture')
            (template / 'nginx.conf').write_text('fixture')
            (template / 'broker-start.sh').write_text('fixture')
            def api(path, token):
                if path == 'commits/main':
                    return {'sha': self.request['revision']}
                return {'workflow_runs': [{'head_sha': self.request['revision'], 'head_repository': {'full_name': deployer.REPOSITORY}, 'conclusion': 'success', 'event': 'push'}]}
            def command(args, **kwargs):
                if args[:3] == ['docker', 'image', 'inspect']:
                    return json.dumps({'io.unlimitedtalk.schema':'0003_contacts','org.opencontainers.image.revision': self.request['revision'], 'org.opencontainers.image.source': 'https://github.com/' + deployer.REPOSITORY})
                return ''
            calls = []
            def compose(release, *args, **kwargs):
                calls.append((release, args))
                if args[:1] == ('config',):
                    return json.dumps({'name': 'unlimited-talk-staging-managed', 'services': {'api': {'image': self.request['image']}, 'migrate': {'image': self.request['image']}, 'gateway': {},'broker': {},'worker': {'image':self.request['image']},'dispatcher': {'image':self.request['image']}}})
                return ''
            real_tempdir = tempfile.TemporaryDirectory
            def temporary_credentials(**kwargs):
                return real_tempdir(dir=root)
            with patch.object(deployer, 'ROOT', config), patch.object(deployer, 'BASE', base), patch.object(deployer, 'TEMPLATE', template), patch.object(deployer, 'github', side_effect=api), patch.object(deployer, 'run', side_effect=command), patch.object(deployer, 'compose', side_effect=compose), patch.object(deployer, 'check_health', side_effect=[{'migration':'0002_identity','revision':'423e16b69b5ffbb2f2d7fd4846e0f50f90eaef3e'},RuntimeError('unhealthy'), {'status': 'ready'}]), patch.object(deployer.tempfile, 'TemporaryDirectory', side_effect=temporary_credentials):
                with self.assertRaisesRegex(RuntimeError, 'previous application restored'):
                    deployer.deploy(self.request)
            self.assertEqual((base / 'current').resolve(), previous)
            self.assertTrue(any(path == previous and args[0] == 'up' for path, args in calls))
            self.assertFalse(any('downgrade' in args for _, args in calls))


if __name__ == '__main__':
    unittest.main()

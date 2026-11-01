"""Boot recovery preserves the deployed mode and never starts a migrator."""
import copy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2] / 'scripts/resume_managed_runtime.py'
spec = importlib.util.spec_from_file_location('resume_runtime', path)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeResumeTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'revision': 'a' * 40,
                         'image': 'ghcr.io/climatsynergie/unlimited-talk-api@sha256:' + 'b' * 64}
        self.config = {'services': {name: {'image': self.manifest['image'] if name in runtime.APPLICATIONS else name}
                                    for name in runtime.SERVICES}}
        self.rows = {name: {'Id': name, 'State': {'Running': False}, 'Config': {
            'Image': self.config['services'][name]['image'], 'Env': ['COMMUNICATIONS_MODE=manual'],
            'Labels': {'org.opencontainers.image.revision': self.manifest['revision'], 'io.unlimitedtalk.schema': '0010_dialer'}}}
            for name in runtime.SERVICES}

    def test_existing_mode_wins_over_the_closed_compose_template(self):
        for mode in ('manual', 'webhooks_only'):
            self.rows['api']['Config']['Env'] = ['COMMUNICATIONS_MODE=' + mode]
            self.assertEqual(runtime.validate(self.rows, self.manifest, self.config), mode)

    def test_only_stopped_existing_service_ids_are_started(self):
        self.rows['api']['State']['Running'] = True
        commands = []
        runtime.start_existing(self.rows, commands.append)
        self.assertEqual(commands, [['docker', 'start', name] for name in runtime.SERVICES if name != 'api'])
        self.assertNotIn('migrate', str(commands))

    def test_missing_mismatched_or_unknown_runtime_is_rejected(self):
        for alteration in ('missing', 'image', 'revision', 'mode'):
            rows = copy.deepcopy(self.rows)
            if alteration == 'missing': del rows['worker']
            elif alteration == 'image': rows['api']['Config']['Image'] = 'untrusted:latest'
            elif alteration == 'revision': rows['worker']['Config']['Labels']['org.opencontainers.image.revision'] = 'c' * 40
            else: rows['api']['Config']['Env'] = ['COMMUNICATIONS_MODE=live']
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                runtime.validate(rows, self.manifest, self.config)

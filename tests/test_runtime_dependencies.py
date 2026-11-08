"""Artifact policy: reviewed runtime lock only, without package installers.

Execute inside the built application image; this inspects installed artifacts,
not Dockerfile text, and neither installs packages nor contacts a network.
"""
import importlib.metadata as metadata
import importlib.util
from pathlib import Path
import re
import shutil
import unittest


def normalized(name):
    return re.sub(r'[-_.]+','-',name).lower()


class RuntimeDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lock=Path('/app/requirements.lock')
        cls.expected={}
        for line in lock.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):continue
            name,separator,version=line.partition('==')
            if not separator or not name or not version:
                raise AssertionError('The reviewed runtime lock must pin exact package versions.')
            key=normalized(name)
            if key in cls.expected:raise AssertionError('Duplicate runtime lock entry: '+key)
            cls.expected[key]=version
        if not cls.expected:raise AssertionError('Runtime requirements lock is empty.')
        cls.actual={normalized(d.metadata['Name']):d.version for d in metadata.distributions()}

    def test_runtime_contains_no_installer_module_or_command(self):
        actual=dict(modules={name:importlib.util.find_spec(name) is not None for name in ('pip','ensurepip')},
                    commands={name:shutil.which(name) for name in ('pip','pip3','pip3.12')})
        expected=dict(modules=dict(pip=False,ensurepip=False),commands={name:None for name in ('pip','pip3','pip3.12')})
        self.assertEqual(actual,expected,'Package installation/bootstrap code must not remain in the runtime image.')

    def test_locked_runtime_versions_are_unchanged(self):
        self.assertEqual({name:self.actual.get(name) for name in self.expected},self.expected)

    def test_runtime_contains_no_unlocked_distributions(self):
        self.assertEqual(set(self.actual),set(self.expected),'Installed inventory must contain exactly the reviewed runtime lock.')

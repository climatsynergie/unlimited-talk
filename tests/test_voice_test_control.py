import copy
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'scripts/control_voice_test.py'
spec=importlib.util.spec_from_file_location('voice_test_operator',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class VoiceTestControlTests(unittest.TestCase):
    def test_override_cannot_change_image_database_network_or_other_workers(self):
        base={'name':'unlimited-talk-staging-managed','services':{
            'api':{'image':'reviewed@sha256:x','environment':{'COMMUNICATIONS_MODE':'webhooks_only','DB_HOST':'private'}},
            'voice-archiver':{'image':'reviewed@sha256:x'}},'networks':{'private':{}}}
        allowed=copy.deepcopy(base);allowed['services']['api']['environment']['COMMUNICATIONS_MODE']='controlled_test'
        module.safe_config(base,allowed)
        for mutate in [lambda v:v['services']['api'].update(image='different'),
            lambda v:v['services']['api']['environment'].update(DB_HOST='public'),
            lambda v:v['services'].update(extra={}),lambda v:v['networks'].update(public={})]:
            candidate=copy.deepcopy(allowed);mutate(candidate)
            with self.assertRaises(ValueError):module.safe_config(base,candidate)

    def test_old_api_or_foreign_image_cannot_be_armed(self):
        revision='a'*40
        labels={'org.opencontainers.image.source':'https://github.com/climatsynergie/unlimited-talk',
                'org.opencontainers.image.revision':revision,'io.unlimitedtalk.schema':'0008_recordings',
                'io.unlimitedtalk.voice-browser':'1','io.unlimitedtalk.voice-runtime':'1','io.unlimitedtalk.voice-archive':'1'}
        module.browser_labels(labels,revision)
        for key in labels:
            candidate=labels.copy();candidate.pop(key)
            with self.assertRaises(ValueError):module.browser_labels(candidate,revision)
        for invalid in [' a'*40,'a'*39,'a'*41,'main','$(anything)']:
            with self.assertRaises(ValueError):module.valid_revision(invalid)

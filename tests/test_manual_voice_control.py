"""The host switch cannot replace images, widen egress or expose business data."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

scripts = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(scripts))
spec = importlib.util.spec_from_file_location('manual_operator',scripts/'control_manual_voice.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class ManualControlTests(unittest.TestCase):
    def test_gateway_dns_delay_cannot_confirm_the_previous_mode(self):
        with patch.object(module,'health',side_effect=[OSError(),{'calling_enabled':False},{'calling_enabled':True}]), \
                patch.object(module.time,'sleep'):
            self.assertTrue(module.wait_health('a'*40,True)['calling_enabled'])
        with patch.object(module,'health',return_value={'calling_enabled':False}), \
                patch.object(module.time,'sleep'), self.assertRaises(RuntimeError):
            module.wait_health('a'*40,True)

    def test_only_api_mode_can_change_in_attested_compose(self):
        base = {'name':'unlimited-talk-staging-managed','services':{
            'api':{'image':'pinned-digest','environment':{'COMMUNICATIONS_MODE':'webhooks_only','DB_HOST':'private'}},
            'voice-archiver':{'image':'pinned-digest'}}}
        candidate = copy.deepcopy(base); candidate['services']['api']['environment']['COMMUNICATIONS_MODE']='manual'
        module.manual_config(base,candidate)
        for alter in [lambda c:c['services']['api'].update(image='other'),
            lambda c:c['services']['api']['environment'].update(DB_HOST='public'),
            lambda c:c['services'].update(extra={})]:
            invalid = copy.deepcopy(candidate); alter(invalid)
            with self.assertRaises(ValueError): module.manual_config(base,invalid)

    def test_profile_conversion_preserves_credentials_and_rejects_ambiguous_versions(self):
        original = dict(version=1,mode='controlled_test',approved_destination='+14165550101',
                        **{key:'synthetic' for key in module.COMMON})
        candidate = module.converted_profile(original)
        self.assertEqual(set(candidate)-set(original), {'max_duration_seconds','max_concurrent_calls'})
        self.assertNotIn('approved_destination',candidate)
        self.assertEqual({key:candidate[key] for key in module.COMMON}, {key:original[key] for key in module.COMMON})
        self.assertEqual(module.converted_profile(candidate),candidate)
        for change in [dict(version=True),dict(mode='live'),dict(unexpected=True)]:
            with self.assertRaises(ValueError): module.converted_profile(original|change)
        for change in [dict(max_concurrent_calls=True),dict(max_duration_seconds=601),dict(approved_destination='hidden-whitelist')]:
            with self.assertRaises(ValueError): module.converted_profile(candidate|change)

    def test_outer_auth_removal_preserves_hooks_and_private_read_gateway(self):
        from prepare_voice_runtime import render_hooks
        original = (scripts.parent/'infrastructure/caddy/Caddyfile').read_text()
        hooks = render_hooks(original)+'\nimport /etc/caddy/unlimited-talk-voice-read.caddy\n'
        candidate = module.public_caddy(hooks)
        self.assertNotIn('import /etc/caddy/staging-access.caddy',candidate)
        self.assertIn('respond @unlimited_talk_internal 404',candidate)
        self.assertIn('path_regexp voice',candidate)
        self.assertTrue(candidate.endswith('import /etc/caddy/unlimited-talk-voice-read.caddy\n'))
        self.assertEqual(module.public_caddy(candidate),candidate)
        for unexpected in [original,hooks+hooks,candidate+'\n\t\t\timport /etc/caddy/staging-access.caddy\n']:
            with self.assertRaises(ValueError): module.public_caddy(unexpected)

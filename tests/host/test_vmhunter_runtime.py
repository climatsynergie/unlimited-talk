import copy
import importlib.util
import ipaddress
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
from types import SimpleNamespace

path=Path(__file__).resolve().parents[2]/'scripts/vmhunter_runtime.py'
spec=importlib.util.spec_from_file_location('vm_runtime',path)
vm=importlib.util.module_from_spec(spec);spec.loader.exec_module(vm)

class RuntimeTests(unittest.TestCase):
    def fixture(self):
        return dict(name='unlimited-talk-staging-managed',services={
            'api':{'image':'ghcr.io/climatsynergie/unlimited-talk-api@sha256:'+'a'*64,
                   'environment':{'COMMUNICATIONS_MODE':'webhooks_only','DB_HOST':'private.invalid','IDENTITY_KEY_FILE':'private','SPACES_CONFIG_FILE':'private'},
                   'secrets':['postgres_ca','runtime_password','voice_profile']},
            'gateway':{'image':'same'},'worker':{'image':'same'}},
            secrets={k:{'file':'/private/'+k} for k in ('postgres_ca','runtime_password','voice_profile')},
            networks={'staging':{'name':'unlimited-talk-staging-managed_staging'}})
    def test_only_api_policy_mount_changes_and_patch_is_idempotent(self):
        original=self.fixture();before=copy.deepcopy(original);patched=vm.patched_compose(original)
        self.assertEqual(original,before)
        self.assertEqual(patched['services']['gateway'],original['services']['gateway'])
        self.assertEqual(patched['services']['worker'],original['services']['worker'])
        self.assertEqual(patched['services']['api']['image'],original['services']['api']['image'])
        self.assertEqual(patched['services']['api']['environment']['COMMUNICATIONS_MODE'],'webhooks_only')
        self.assertEqual(patched['services']['api']['secrets'][-1],'vmhunter_pilot')
        self.assertEqual(vm.patched_compose(patched),patched)
    def test_gateway_preserves_existing_routes_and_has_only_public_media_proxy(self):
        original='server {\n    resolver 127.0.0.11 valid=5s ipv6=off;\n    location / { proxy_pass http://api; }\n}\n'
        value=vm.patched_gateway(original)
        self.assertEqual(value.replace(vm.MEDIA,''),original)
        self.assertEqual(vm.patched_gateway(value),value)
        self.assertIn('limit_except GET',value)
        self.assertNotIn('/private/observe',value)
        with self.assertRaises(ValueError):vm.patched_gateway('unexpected')
    def test_only_approved_public_ipv4_hosts_can_be_admitted(self):
        seen=[]
        def resolver(host,port,family,kind):
            seen.append((host,port,family,kind));return [(None,None,None,None,('1.1.1.1',443))]
        self.assertEqual(vm.provider_addresses(resolver),['1.1.1.1'])
        self.assertEqual([v[0] for v in seen],list(vm.HOSTS))
        for address in ('127.0.0.1','10.0.0.1','172.30.8.1','169.254.169.254'):
            with self.assertRaises(ValueError):vm.provider_addresses(lambda *args:[(None,None,None,None,(address,443))])
        with self.assertRaises(ValueError):vm.provider_addresses(lambda *args:[])
    def test_sidecar_is_pinned_nonroot_private_and_has_only_five_secrets(self):
        value=vm.standalone(self.fixture());service=value['services']['vmhunter']
        self.assertNotIn('ports',service);self.assertTrue(service['read_only'])
        self.assertEqual(service['user'],'10001:10001');self.assertEqual(service['cap_drop'],['ALL'])
        self.assertEqual(set(service['secrets']),{'postgres_ca','runtime_password','voice_profile','vmhunter_pilot','vmhunter_credentials'})
        self.assertNotIn('IDENTITY_KEY_FILE',service['environment'])
        self.assertNotIn('SPACES_CONFIG_FILE',service['environment'])
        self.assertEqual(service['networks']['staging']['ipv4_address'],vm.ADDRESS)
        self.assertEqual(service['restart'],'unless-stopped')
        self.assertTrue(value['networks']['staging']['external'])
        changed=self.fixture();changed['services']['api']['image']='untrusted:latest'
        with self.assertRaises(ValueError):vm.standalone(changed)

    def test_firewall_change_is_scoped_to_one_container_and_provider_https(self):
        calls=[]
        def execute(command,**kwargs):
            calls.append(command)
            return '-N '+vm.CHAIN if command==['iptables','-S',vm.CHAIN] else ''
        with patch.object(vm,'provider_addresses',return_value=['1.1.1.1']), patch.object(vm,'run',side_effect=execute), patch.object(vm.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
            vm.refresh_egress()
        self.assertIn(['iptables','-I','UT-STAGING-EGRESS','1','-s',vm.ADDRESS+'/32','-j',vm.CHAIN],calls)
        accepts=[command for command in calls if 'ACCEPT' in command]
        self.assertEqual(accepts,[['iptables','-I',vm.CHAIN,'1','-d','1.1.1.1/32','-p','tcp','--dport','443','-j','ACCEPT']])
        self.assertFalse(any('-F' in command or '0.0.0.0/0' in command for command in calls))

if __name__=='__main__':unittest.main()

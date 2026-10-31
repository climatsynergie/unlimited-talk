"""Private egress renders a fixed provider/account/method policy, not a proxy."""
import importlib.util
from pathlib import Path
import re
import sys
import unittest

scripts=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('voice_runtime_preparation',scripts/'prepare_voice_runtime.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class RuntimePreparationTests(unittest.TestCase):
    def test_firewall_interface_is_bound_to_the_expected_private_network(self):
        network={'Name':'unlimited-talk-staging-managed_staging','Id':'a'*64,
                 'IPAM':{'Config':[{'Subnet':'172.30.8.0/24','Gateway':'172.30.8.1'}]}}
        self.assertEqual(module.private_bridge(network),'br-'+'a'*12)
        for change in [{'Name':'other'},{'Id':'unsafe;command'},{'IPAM':{'Config':[{'Subnet':'0.0.0.0/0','Gateway':'1.1.1.1'}]}}]:
            with self.assertRaises(module.PreflightError):module.private_bridge({**network,**change})

    def test_gateway_regex_allows_only_scoped_resource_reads_with_canonical_query(self):
        config=dict(account_sid='AC'+'a'*32,api_key_sid='SK'+'b'*32,api_key_secret='c'*32)
        rendered=module.render_gateway(config,'d'*64)
        expression=next(line for line in rendered.splitlines() if 'expression' in line)
        import json
        regex=json.loads(expression.split('.matches(',1)[1].rsplit(')',1)[0])
        base='/2010-04-01/Accounts/'+config['account_sid']
        for path in [base+'/Calls/CA'+'1'*32+'.json',base+'/Calls.json?ParentCallSid=CA'+'1'*32+'&PageSize=2']:
            self.assertIsNotNone(re.fullmatch(regex,path))
        for path in [base+'/Calls.json',base+'/Calls.json?PageSize=2',base+'/Calls/CA'+'1'*32+'.json?x=1',
                     base+'/Calls.json?ParentCallSid=CA'+'1'*32+'&PageSize=2&_method=POST',
                     base.replace('a'*32,'f'*32)+'/Calls/CA'+'1'*32+'.json']:
            self.assertIsNone(re.fullmatch(regex,path))
        self.assertIn('bind 172.30.8.1',rendered)
        self.assertIn('reverse_proxy @voice_read https://api.twilio.com',rendered)
        self.assertIn('header_up -X-HTTP-Method-Override',rendered)
        self.assertNotIn('tls_insecure_skip_verify',rendered)
        with self.assertRaises(module.PreflightError):module.render_gateway({**config,'account_sid':'AC\nmalicious'},'d'*64)

    def test_public_exception_is_post_only_and_preserves_existing_access_import(self):
        original='''{$STAGING_DOMAIN} {
\troute {
\t\timport /etc/caddy/staging-access.caddy
\t\treverse_proxy 127.0.0.1:8110 {
\t\t\theader_up -Authorization
\t\t}
\t}
}
'''
        rendered=module.render_hooks(original)
        self.assertIn('method POST',rendered)
        self.assertEqual(rendered.count('import /etc/caddy/staging-access.caddy'),1)
        self.assertIn('probe|voice|parent-status',rendered)
        self.assertNotIn('/api/telephony/test',rendered)
        self.assertEqual(module.render_hooks(rendered),rendered)
        with self.assertRaises(module.PreflightError):module.render_hooks('unreviewed configuration')

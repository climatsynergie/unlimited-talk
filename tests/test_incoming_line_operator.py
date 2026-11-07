import importlib.util
from pathlib import Path
import sys,unittest
from unittest.mock import patch
folder=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(folder))
spec=importlib.util.spec_from_file_location('incoming_line_operator',folder/'connect_incoming_line.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class IncomingLineOperatorTests(unittest.TestCase):
 def test_only_selected_voice_number_and_canonical_hooks_are_accepted(self):
  account='AC'+'a'*32;pn='PN'+'b'*32;phone='+14165550101'
  number=dict(account_sid=account,sid=pn,phone_number=phone,capabilities={'voice':True})
  self.assertEqual(module.checked(number,account,pn,phone),{key:'' for key in module.FIELDS})
  for changed in [{'account_sid':'AC'+'c'*32},{'sid':'PN'+'d'*32},{'phone_number':'+14165550102'},{'capabilities':{'voice':False}}]:
   with self.assertRaises(ValueError):module.checked(number|changed,account,pn,phone)
  desired=module.desired('https://voice.example.invalid')
  self.assertTrue(desired['voice_url'].endswith('/api/telephony/twilio/incoming'))
  self.assertTrue(desired['status_callback'].endswith('/incoming-parent-status'))
  self.assertEqual(desired['trunk_sid'],'');self.assertEqual(desired['voice_application_sid'],'')
  for origin in ['http://voice.example.invalid','https://voice.example.invalid/x','https://user@voice.example.invalid','https://voice.example.invalid?x=1']:
   with self.assertRaises(ValueError):module.desired(origin)
 def test_provider_cannot_purchase_originate_or_write_other_resources(self):
  provider=module.Provider(dict(account_sid='AC'+'a'*32,api_key_sid='SK'+'b'*32,api_key_secret='secret'),'PN'+'c'*32)
  self.assertEqual(provider.url,'https://api.twilio.com/2010-04-01/Accounts/AC'+'a'*32+'/IncomingPhoneNumbers/PN'+'c'*32+'.json')
  with patch.object(module.urllib.request,'build_opener') as network:
   for method,body in [('DELETE',None),('PUT',{}),('POST',{'To':'+14165550102'}),('POST',{'VoiceUrl':'https://other.invalid'})]:
    with self.assertRaises(ValueError):provider.request(method,body)
   network.assert_not_called()

 def test_database_command_remains_parameterized_and_contains_no_migration(self):
  import ast,json
  values=dict(queue='00000000-0000-0000-0000-000000000001',phone='+14165550101',version=1,account='AC'+'a'*32,pn='PN'+'b'*32,origin='https://voice.example.invalid')
  for action in ['inspect','connecting','active','disconnected']:
   with patch.object(module,'run',return_value=json.dumps({'verified':True})) as run:
    module.database(['docker','compose'],action,values)
    code=run.call_args.kwargs['data'];ast.parse(code)
    self.assertNotIn('__VALUES__',code);self.assertIn('VALUES (:queue,:account,:pn,:phone,:origin',code)
    self.assertNotIn('ALTER TABLE',code);self.assertNotIn('CREATE TABLE',code)

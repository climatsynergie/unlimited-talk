"""No network: deployment requests cannot bypass successful exact-main CI."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

spec=importlib.util.spec_from_file_location('campaign_release',Path(__file__).resolve().parents[2]/'scripts/dispatch_campaign_release.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
SHA='a'*40
class CampaignReleaseTests(unittest.TestCase):
    def request(self):return dict(version=1,request_id=str(uuid4()),campaign_ids=sorted(module.CAMPAIGNS),owner_requested_deployment=True)
    def run_record(self):return dict(head_sha=SHA,head_branch='main',head_repository={'full_name':module.REPOSITORY},event='push',status='completed',conclusion='success')
    def test_request_requires_exact_explicit_campaigns_and_owner_intent(self):
        self.assertTrue(module.validate_request(self.request()))
        for change in ({'campaign_ids':[]},{'campaign_ids':['*']},{'owner_requested_deployment':False},
                {'version':True},{'request_id':'invalid'},{'extra':True}):
            with self.subTest(change=change),self.assertRaises((ValueError,TypeError,AttributeError)):
                module.validate_request(self.request() | change)
    def test_foreign_source_pr_branch_or_failed_ci_cannot_satisfy_release(self):
        for change in ({'head_sha':'b'*40},{'head_branch':'qa/example'},
                {'head_repository':{'full_name':'foreign/repo'}},{'event':'pull_request'},{'conclusion':'failure'}):
            self.assertFalse(module.successful_run([self.run_record() | change],SHA))
    def test_success_dispatches_only_existing_normal_protected_workflow(self):
        with patch.object(module,'github',side_effect=[{'sha':SHA},{'workflow_runs':[self.run_record()]}]),patch.object(module,'run') as run:
            module.dispatch(SHA)
        run.assert_called_once_with(['workflow','run','deploy-staging.yml','--repo',module.REPOSITORY,'--ref','main','-f','revision='+SHA])
    def test_changed_main_stops_before_dispatch(self):
        with patch.object(module,'github',return_value={'sha':'b'*40}),patch.object(module,'run') as run:
            with self.assertRaises(RuntimeError):module.dispatch(SHA)
        run.assert_not_called()
    def test_failed_ci_stops_before_dispatch(self):
        with patch.object(module,'github',side_effect=[{'sha':SHA},{'workflow_runs':[self.run_record() | {'conclusion':'failure'}]}]),patch.object(module,'run') as run:
            with self.assertRaises(RuntimeError):module.dispatch(SHA)
        run.assert_not_called()
    def test_waiting_request_has_no_deployment_side_effect(self):
        with patch.object(module,'github',side_effect=[{'sha':SHA},{'workflow_runs':[]}]),patch.object(module.time,'monotonic',side_effect=[0,0,3000]),patch.object(module.time,'sleep'),patch.object(module,'run') as run:
            with self.assertRaises(TimeoutError):module.dispatch(SHA)
        run.assert_not_called()

spec=importlib.util.spec_from_file_location('campaign_configuration',Path(__file__).resolve().parents[2]/'scripts/configure_vmhunter_campaigns.py')
configuration=importlib.util.module_from_spec(spec);spec.loader.exec_module(configuration)
class CampaignConfigurationTests(unittest.TestCase):
    def previous(self):return dict(version=3,pilot_id=str(uuid4()),campaign_id=configuration.CAMPAIGNS[0],scope='campaign',mode='screen',enabled=True,agent_ids=[],test_numbers=[],audio_approved=True,screening_approved=True,max_analyses=500)
    def test_expansion_preserves_budget_and_pilot_without_agent_snapshot(self):
        previous=self.previous();result=configuration.candidate_policy(previous)
        self.assertEqual(result['pilot_id'],previous['pilot_id'])
        self.assertEqual(result['max_analyses'],500)
        self.assertEqual(result['campaign_ids'],configuration.CAMPAIGNS)
        self.assertNotIn('campaign_id',result)
        self.assertEqual(result['agent_ids'],[])
        self.assertEqual(previous['version'],3)
    def test_unknown_scope_or_missing_audio_approval_cannot_expand(self):
        for change in ({'version':2},{'campaign_id':str(uuid4())},{'scope':'all'},{'audio_approved':False},
                {'screening_approved':False},{'agent_ids':[str(uuid4())]},{'test_numbers':['+14165550101']}):
            with self.subTest(change=change),self.assertRaises(ValueError):configuration.candidate_policy(self.previous() | change)

    def test_explicit_expansion_of_v4_policy_preserves_quota_and_scope(self):
        previous=configuration.candidate_policy(self.previous())
        selected=[*configuration.CAMPAIGNS,str(uuid4())]
        value=configuration.candidate_policy(previous,selected)
        self.assertEqual(value['campaign_ids'],selected)
        self.assertEqual(value['pilot_id'],previous['pilot_id'])
        self.assertEqual(value['max_analyses'],500)
        self.assertEqual(previous['campaign_ids'],configuration.CAMPAIGNS)
        self.assertEqual(value['agent_ids'],[])
        for invalid in ([],['*'],[selected[0],selected[0]],[str(uuid4()) for _ in range(21)]):
            with self.subTest(invalid=invalid),self.assertRaises((ValueError,TypeError)):
                configuration.candidate_policy(previous,invalid)
        with self.assertRaises(ValueError):configuration.candidate_policy(previous | {'audio_approved':False},selected)

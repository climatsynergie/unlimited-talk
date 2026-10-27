import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

path=Path(__file__).resolve().parents[1]/'scripts/deploy_staging.py'
spec=importlib.util.spec_from_file_location('deployer_contacts',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContactsDeploymentTests(unittest.TestCase):
    def test_schema_three_requires_the_deployed_compatible_predecessor(self):
        labels={'io.unlimitedtalk.schema':'0003_contacts'}
        for running in [dict(migration='0003_contacts',revision='a'*40),dict(migration='0002_identity',revision='423e16b69b5ffbb2f2d7fd4846e0f50f90eaef3e')]:
            with patch.object(module,'check_health',return_value=running):
                module.require_identity_rollback_target(labels)
        for running in [{},dict(migration='0002_identity',revision='d9cec5aa0943c9357f08a97b3e72e3922d500aad'),dict(migration='0001_foundation')]:
            with patch.object(module,'check_health',return_value=running),self.assertRaises(ValueError):
                module.require_identity_rollback_target(labels)


    def test_campaign_schema_requires_the_compatible_predecessor(self):
        labels={'io.unlimitedtalk.schema':'0004_campaigns'}
        for running in [dict(migration='0004_campaigns',revision='a'*40),dict(migration='0003_contacts',revision='911177b3181d849115fa5cedd00dd4a21cfcda60')]:
            with patch.object(module,'check_health',return_value=running):module.require_identity_rollback_target(labels)
        for running in [{},dict(migration='0003_contacts',revision='d548e6e048f0265fdb327e906bf80f0b4745af93')]:
            with patch.object(module,'check_health',return_value=running),self.assertRaises(ValueError):module.require_identity_rollback_target(labels)

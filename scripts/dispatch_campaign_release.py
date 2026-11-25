"""Dispatch the normal protected deployment for an explicit owner release request.

Runs only on a main-branch change to the dedicated request manifest. Waits for
exact-source Foundation CI; does not access SSH secrets or bypass the deployer.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import UUID

REPOSITORY='climatsynergie/unlimited-talk'
CAMPAIGNS={'2bdf5195-0b52-49b1-aecc-0caaf5459e77','c137b9e3-149e-4d0b-b814-3c067258b6b8'}

def validate_request(value):
    if (not isinstance(value,dict) or set(value)!={'version','request_id','campaign_ids','owner_requested_deployment'}
            or type(value['version']) is not int or value['version']!=1
            or value['owner_requested_deployment'] is not True
            or not isinstance(value['campaign_ids'],list) or len(value['campaign_ids'])!=2
            or not all(isinstance(c,str) for c in value['campaign_ids'])
            or set(value['campaign_ids'])!=CAMPAIGNS):
        raise ValueError('Invalid campaign release request')
    UUID(value['request_id'])
    return value

def run(args):
    result=subprocess.run(['gh',*args],capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError('GitHub release operation failed')
    return result.stdout

def github(path):
    return json.loads(run(['api','repos/'+REPOSITORY+'/'+path]))

def successful_run(runs,revision):
    return any(r.get('head_sha')==revision and r.get('head_branch')=='main'
        and r.get('head_repository',{}).get('full_name')==REPOSITORY
        and r.get('event')=='push' and r.get('conclusion')=='success' for r in runs)

def dispatch(revision,*,deadline_seconds=2100):
    if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('Complete source revision required')
    deadline=time.monotonic()+deadline_seconds
    while time.monotonic()<deadline:
        if github('commits/main').get('sha')!=revision:
            raise RuntimeError('Main changed; deployment request stopped')
        runs=github('actions/workflows/ci.yml/runs?head_sha='+revision+'&branch=main')['workflow_runs']
        if successful_run(runs,revision):
            run(['workflow','run','deploy-staging.yml','--repo',REPOSITORY,'--ref','main','-f','revision='+revision])
            print('Normal protected deployment requested for '+revision,flush=True)
            return
        if runs and all(r.get('status')=='completed' for r in runs):
            raise RuntimeError('Foundation CI did not pass; deployment stopped')
        print('Waiting for exact-source Foundation CI',flush=True)
        time.sleep(20)
    raise TimeoutError('Foundation CI did not finish before the deployment request deadline')

if __name__=='__main__':
    assert os.environ.get('GITHUB_REPOSITORY')==REPOSITORY and os.environ.get('GITHUB_REF')=='refs/heads/main'
    request=Path('deployment/vmhunter/cvc-release-request.json')
    assert request.stat().st_size<2048
    validate_request(json.loads(request.read_text()))
    dispatch(os.environ['GITHUB_SHA'])

#!/usr/bin/env python3
"""Root console launcher for the deployed application's one-time bootstrap."""
import os
from pathlib import Path
import subprocess
import sys

if os.geteuid()!=0 or not sys.stdin.isatty():
    raise SystemExit('Utilisez la console interactive du serveur staging en administrateur.')
release=Path('/srv/unlimited-talk-staging/current').resolve(strict=True)
subprocess.run(['docker','compose','--project-directory',str(release),
                '--env-file',str(release/'.env'),'-f',str(release/'compose.managed.yaml'),
                'exec','api','python','-m','app.identity.bootstrap'],check=True)

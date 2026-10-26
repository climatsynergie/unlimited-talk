#!/usr/bin/env python3
"""Root console launcher for the deployed application's one-time bootstrap."""
import os
from pathlib import Path
import subprocess
import sys

# Keep the deployed image immutable. The console adapter also handles validation
# gracefully when the preceding application version is still running.
CONSOLE = '''from app.identity.bootstrap import main
messages = {
    'Adresse email invalide',
    'Adresse courriel invalide',
    'Le mot de passe doit contenir entre 12 et 128 caractères',
    'Le mot de passe doit contenir entre 15 et 128 caractères',
    'Choisissez un mot de passe moins prévisible',
}
while True:
    try:
        main()
        break
    except ValueError as error:
        if str(error) not in messages:
            raise SystemExit('Initialisation interrompue. Contactez votre administrateur.') from None
        print(str(error) + '. Aucun compte créé. Recommencez la saisie.')
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('Saisie annulée. Aucun compte créé.') from None
'''


def main():
    if os.geteuid()!=0 or not sys.stdin.isatty():
        raise SystemExit('Utilisez la console interactive du serveur staging en administrateur.')
    release=Path('/srv/unlimited-talk-staging/current').resolve(strict=True)
    result=subprocess.run(['docker','compose','--project-directory',str(release),
                          '--env-file',str(release/'.env'),'-f',str(release/'compose.managed.yaml'),
                          'exec','api','python','-c',CONSOLE],check=False)
    raise SystemExit(result.returncode)


if __name__=='__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('Saisie annulée.') from None

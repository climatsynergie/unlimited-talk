"""Saisie masquée réservée à root, sans connexion réseau ni activation de campagne."""
import argparse
import getpass
import json
import os
from pathlib import Path
import stat
import sys
import warnings

CONFIG = Path('/etc/unlimited-talk-staging/vmhunter-credentials.json')
ENDPOINT = 'wss://app.vmhunter.com/ws'
MAX_BYTES = 8192


class CredentialError(ValueError):
    pass


def validate(value):
    if (not isinstance(value, dict)
            or set(value) != {'version', 'mode', 'endpoint', 'api_key'}
            or type(value['version']) is not int or value['version'] != 1
            or value['mode'] != 'credentials_only' or value['endpoint'] != ENDPOINT):
        raise CredentialError('Configuration VM Hunter invalide.')
    key = value['api_key']
    # The provider key is opaque: do not invent a SID prefix or key format.
    if (not isinstance(key, str) or not 1 <= len(key) <= 2048
            or not key.isascii() or not key.isprintable()
            or any(character.isspace() for character in key)):
        raise CredentialError('Collez uniquement la clé API VM Hunter, sans espace.')
    return value


def private_parent(path):
    info = path.parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise CredentialError('Le dossier doit être privé et appartenir à l’utilisateur courant.')


def collect(prompt=None):
    prompt = prompt or getpass.getpass
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        key = prompt('Clé API VM Hunter (invisible) : ')
        confirmation = prompt('Confirmez la clé API (invisible) : ')
    if key != confirmation:
        raise CredentialError('Les deux saisies sont différentes. Aucun enregistrement.')
    return validate(dict(version=1, mode='credentials_only', endpoint=ENDPOINT, api_key=key))


def store(value, path):
    validate(value)
    private_parent(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def load(path):
    private_parent(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise CredentialError('Le fichier doit être privé, régulier et en mode 600.')
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CredentialError('Fichier VM Hunter trop volumineux.')
    try:
        return validate(json.loads(raw))
    except (ValueError, UnicodeError, TypeError):
        raise CredentialError('Configuration VM Hunter invalide.') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='store', choices=['store', 'status'])
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise CredentialError('Exécutez cette commande dans le terminal root du serveur.')
        if args.action == 'status':
            load(CONFIG)
            print('Clé VM Hunter enregistrée dans un fichier privé. Sa validité auprès du fournisseur reste à vérifier.')
            return 0
        private_parent(CONFIG)
        if CONFIG.exists() or CONFIG.is_symlink():
            raise CredentialError('Une clé VM Hunter existe déjà. Aucun remplacement.')
        store(collect(), CONFIG)
        print('Clé VM Hunter enregistrée dans un fichier privé.')
        print('Aucune connexion au fournisseur et aucune activation de campagne effectuées.')
        return 0
    except CredentialError as error:
        print(str(error), file=sys.stderr)
    except FileExistsError:
        print('Un fichier existe déjà. Aucun remplacement.', file=sys.stderr)
    except FileNotFoundError:
        print('La clé VM Hunter ou son dossier privé est absent.', file=sys.stderr)
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print('Saisie interrompue. Utilisez un terminal interactif ; aucun secret affiché.', file=sys.stderr)
    except Exception:
        # Filesystem errors and malformed files must never echo their contents.
        print('Enregistrement interrompu. Aucun secret affiché ; vérifiez le fichier privé.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

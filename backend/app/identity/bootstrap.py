"""Interactive, one-time first administrator setup. No public bootstrap route."""
import getpass
import os
import sys
import uuid

import pyotp

from app.database import make_engine
from app.identity.security import email_address, encryption_key, hash_password, otp_counter, validate_password
from app.identity.service import ADMIN_LOCK, audit, query, recovery_codes


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Utilisez une console interactive; ne transmettez pas les secrets en arguments.')
    engine = make_engine()
    try:
        with engine.connect() as db:
            if query(db,'SELECT EXISTS(SELECT 1 FROM staging.identity_users)').scalar_one():
                raise SystemExit('Initialisation déjà effectuée. Utilisez les invitations administrateur.')
        email = email_address(input('Email du premier administrateur : '))
        name = input('Nom affiché : ').strip()
        if not 1<=len(name)<=200:
            raise SystemExit('Nom invalide')
        password = getpass.getpass('Mot de passe individuel (15 caractères minimum) : ')
        if password != getpass.getpass('Confirmez le mot de passe : '):
            raise SystemExit('Les mots de passe sont différents. Aucun compte créé.')
        encoded = hash_password(validate_password(password))
        secret = pyotp.random_base32()
        print('Ajoutez ce secret dans votre application Authenticator (ne le partagez pas) :')
        print(secret)
        print('Compte :',email,'— émetteur : Unlimited Talks Staging')
        counter = otp_counter(secret,getpass.getpass('Code à 6 chiffres de votre Authenticator : '),-1)
        if counter is None:
            raise SystemExit('Code invalide. Aucun compte créé.')
        cipher = encryption_key(os.environ['IDENTITY_KEY_FILE'])
        identifier = uuid.uuid4()
        with engine.begin() as db:
            query(db,'SELECT pg_advisory_xact_lock(:key)',key=ADMIN_LOCK)
            if query(db,'SELECT EXISTS(SELECT 1 FROM staging.identity_users)').scalar_one():
                raise SystemExit('Un compte existe déjà. Aucun autre compte créé.')
            query(db,'''INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret,mfa_last_counter)
                VALUES (:id,:email,:name,'admin',:hash,:secret,:counter)''',id=identifier,email=email,
                name=name,hash=encoded,secret=cipher.encrypt(secret.encode()).decode(),counter=counter)
            codes = recovery_codes(db,identifier)
            audit(db,identifier,'user.bootstrap_admin',identifier)
        print('Administrateur créé avec MFA. Conservez ces codes de récupération à usage unique :')
        for code in codes:
            print(code)
        print('Enregistrez ces codes dans votre gestionnaire de mots de passe. Ne les collez pas dans le chat.')
    finally:
        engine.dispose()


if __name__=='__main__':
    main()

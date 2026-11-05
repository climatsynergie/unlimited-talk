"""Bounded continuity for a previously verified caller during provider read outages."""
from app.identity.service import query

# A successful inventory that removes/disables a number always wins. Grace is
# limited to one additional day and only to a provider-availability failure,
# never an invalid response or a number whose ownership was never established.
VERIFICATION_COLUMNS = '''n.verified_at>clock_timestamp()-interval '24 hours' AS fresh,
    coalesce((n.verified_at<=clock_timestamp()-interval '24 hours'
     AND n.verified_at>clock_timestamp()-interval '48 hours'
     AND directory.last_error_code='provider_unavailable'),false) AS in_grace'''
DIRECTORY_JOIN = 'LEFT JOIN staging.voice_directory_state directory ON directory.account_sid=n.account_sid'


def status(db,account):
    if not account:return None
    row=query(db,'''SELECT synchronized_at,last_error_code,
        extract(epoch FROM clock_timestamp()-synchronized_at)::bigint AS age_seconds
        FROM staging.voice_directory_state WHERE account_sid=:account''',account=account).mappings().first()
    if not row or row['age_seconds'] is None:
        return dict(severity='critical',message='La vérification des numéros Twilio attend sa première synchronisation.')
    age=row['age_seconds']
    if age<12*3600:return None
    grace=row['last_error_code']=='provider_unavailable' and age<48*3600
    if age>=24*3600 and not grace:
        return dict(severity='critical',message='La vérification des numéros Twilio a expiré. Contrôlez la connexion et relancez la synchronisation.')
    return dict(severity='warning',message=(
        'Twilio ne répond pas à la vérification des numéros. Les numéros déjà validés bénéficient d’une continuité limitée à 48 heures depuis leur dernière vérification.'
        if age>=24*3600 else
        'La synchronisation des numéros Twilio est en retard. Vérifiez la connexion avant l’expiration des vérifications.'))

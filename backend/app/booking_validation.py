"""Allowlisted field feedback for booking/qualification; auth stays redacted."""
from app.qualification import QualificationError, SCHEMAS

ROUTES = frozenset({
    '/api/calendar', '/api/calendar/{identifier}', '/api/calendar/resolve',
    '/api/campaigns/{identifier}/contacts/{contact_id}/qualification',
})
LABELS = {field['key']: field['label'] for schema in SCHEMAS.values() for field in schema['fields']}
SCHEDULE = {
    'local_start': 'Date et heure du rendez-vous invalides. Sélectionnez une date et une heure dans le calendrier.',
    'timezone': 'Fuseau horaire invalide. Choisissez un fuseau dans la liste.',
    'utc_offset_minutes': 'Décalage horaire invalide. Choisissez une des heures proposées par le calendrier.',
    'duration_minutes': 'Durée du rendez-vous invalide : indiquez un nombre entier entre 5 et 1440 minutes.',
    'notes': 'Les notes du rendez-vous dépassent la limite de 5000 caractères.',
    'membership_version': 'La version de la fiche du contact est invalide. Conservez vos réponses avant de recharger la fiche.',
    'qualification_revision': 'La référence de qualification est invalide. Conservez vos réponses avant de recharger la fiche.',
}


def feedback(route, errors):
    if route not in ROUTES:
        return None
    messages = []
    for item in errors:
        loc = tuple(item.get('loc', ()))
        reason = (item.get('ctx') or {}).get('error')
        message = code = None
        if 'qualification' in loc:
            if isinstance(reason, QualificationError):
                field = reason.field
                label = LABELS.get(field)
                if label and reason.reason == 'text':
                    message = 'Le champ « ' + label + ' » contient un caractère non pris en charge.'
                elif reason.reason == 'shape':
                    message = 'La qualification contient un champ non reconnu. Conservez votre saisie et contactez l’administrateur.'
                if message:
                    code = 'qualification.' + (field if field in LABELS else 'format')
            elif loc and loc[-1] in LABELS:
                message = 'Vérifiez le texte du champ « ' + LABELS[loc[-1]] + ' ».'
                code = 'qualification.' + loc[-1]
            elif loc and loc[-1] == 'schema_version':
                message = 'Version du questionnaire invalide. Conservez votre saisie et contactez l’administrateur.'
                code = 'qualification.schema_version'
        elif len(loc) >= 2 and loc[0] in ('body', 'query') and loc[1] in SCHEDULE:
            message, code = SCHEDULE[loc[1]], 'booking.' + loc[1]
        if message and (code, message) not in messages:
            messages.append((code, message))
    if not messages:
        return None
    # Bounded static output. No raw input, exception message or unknown key.
    return ' '.join(message for _, message in messages[:5]), messages[0][0]

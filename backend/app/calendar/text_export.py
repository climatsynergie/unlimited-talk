"""French visit sheets from saved appointment qualifications, without inference."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

MAX_APPOINTMENTS = 1000
MAX_BYTES = 8 * 1024 * 1024
WEEKDAYS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')
MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre')
PHASE_NAMES = dict(booked='RDV booké', confirmed='Confirmé', sold='Vendu', cancelled='Annulé',
                   invalid='Non valide', non_compliant='Non conforme', completed='Terminé', no_show='Absent')
FIELDS = (
    ('owner', 'Propriétaire du logement'), ('owners', 'Nombre de propriétaires'),
    ('owners_present', 'Tous les propriétaires seront présents'),
    ('spouses_present', 'Présence des conjoints'),
    ('property_type', 'Type de propriété'), ('floors', 'Étages hors sous-sol'),
    ('basement', 'Sous-sol'), ('construction_year', 'Année de construction'),
    ('heating', 'Système de chauffage'), ('heating_age', 'Âge du chauffage'),
    ('heating_comment', 'Commentaire — chauffage'), ('heat_pump', 'Thermopompe'),
    ('heat_pump_age', 'Années depuis l’installation de la thermopompe'),
    ('wall_pump_floors', 'Thermopompe murale à tous les étages'),
    ('heat_pump_comment', 'Commentaire — thermopompe'),
    ('insulation', 'Isolation'), ('insulation_comment', 'Commentaire — isolation'),
    ('attic_access', 'Accès au grenier / entretoit'), ('hydro_bill', 'Consommation électrique (Hydro)'),
    ('comments', 'Informations complémentaires'),
)


def day_bounds(day, zone):
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, 'Fuseau horaire invalide.') from None
    if not 2000 <= day.year <= 2100:
        raise HTTPException(422, 'Choisissez une date entre 2000 et 2100.')
    # Consecutive local midnights cover 23/25-hour daylight-saving days.
    return (datetime.combine(day, time(), tz).astimezone(timezone.utc),
            datetime.combine(day + timedelta(days=1), time(), tz).astimezone(timezone.utc))


def french_day(value):
    return f'{WEEKDAYS[value.weekday()]} {value.day} {MONTHS[value.month-1]} {value.year}'


def text(value):
    return value.strip() if isinstance(value, str) else ''


def appointment_text(row, zone):
    starts = row['starts_at']
    if isinstance(starts,str):
        starts = datetime.fromisoformat(starts.replace('Z','+00:00'))
    local = starts.astimezone(ZoneInfo(zone))
    answers = (row.get('qualification') or {}).get('answers') or {}
    profile = row.get('profile') or {}
    name = text(profile.get('display_name')) or ' '.join(filter(None, (text(profile.get('first_name')), text(profile.get('last_name'))))) or 'Non renseigné'
    street = ' '.join(filter(None, (text(answers.get('civic_number')), text(answers.get('street'))))) or text(profile.get('address'))
    locality = ' '.join(filter(None, (text(answers.get('city')) or text(profile.get('city')),
                                     text(profile.get('province')),
                                     text(answers.get('postal_code')) or text(profile.get('postal_code')))))
    address = ', '.join(filter(None, (street, locality))) or 'Non renseignée'
    lines = [f'Rendez-vous : {french_day(local)} à {local:%H} h {local:%M}',
             f'Fuseau horaire : {zone} (UTC{local:%z})',
             f'Statut : {PHASE_NAMES.get(row.get("phase") or row["status"], row["status"])}',
             '', 'Informations du client :', '', f'Nom : {name}',
             f'Téléphone : {row["phone"]}', f'Adresse : {address}', '']
    for key, label in FIELDS:
        value = text(answers.get(key))
        if value:
            lines.append(f'{label} : {value}')
    if not any(text(value) for value in answers.values()):
        lines.append('Qualification : non renseignée pour ce rendez-vous.')
    if text(row.get('notes')):
        lines.extend(('', f'Notes du rendez-vous : {text(row["notes"])}'))
    lines.extend(('', f'Booker par : {row["creator_name"]}', f'Campagne : {row["campaign_name"]}'))
    return '\n'.join(lines)


def render(day, zone, rows):
    parts = [f'Unlimited Talks — Rendez-vous du {french_day(day)}\nFuseau horaire : {zone}\n{len(rows)} rendez-vous\n']
    size = len(parts[0].encode('utf-8')) + 3
    for row in rows:
        part = '\n' + '='*64 + '\n\n' + appointment_text(row, zone) + '\n'
        size += len(part.encode('utf-8'))
        if size > MAX_BYTES:
            raise HTTPException(422, 'Le fichier est trop volumineux. Filtrez les rendez-vous par agent.')
        parts.append(part)
    # UTF-8 BOM supports accents in Windows text editors; never export HTML.
    return ('\ufeff' + ''.join(parts)).encode('utf-8')

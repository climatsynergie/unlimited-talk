"""Resolve wall-clock input without guessing through DST transitions."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException


def possibilities(local: datetime, zone: str):
    if not 2000 <= local.year <= 2100 or local.second or local.microsecond:
        raise HTTPException(422,'Choisissez une date entre 2000 et 2100, à la minute près.')
    if local.tzinfo is not None:
        raise HTTPException(422,'Indiquez une heure locale sans décalage.')
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422,'Fuseau horaire invalide.') from None
    candidates = {}
    for fold in (0, 1):
        aware = local.replace(tzinfo=tz, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None) == local:
            minutes = int(aware.utcoffset().total_seconds() / 60)
            candidates[utc] = {'starts_at': utc, 'utc_offset_minutes': minutes,
                               'label': 'UTC'+('+' if minutes>=0 else '−')+f'{abs(minutes)//60:02}:{abs(minutes)%60:02}'}
    return [candidates[k] for k in sorted(candidates)]


def resolve(local, zone, offset):
    choices = possibilities(local, zone)
    if not choices:
        raise HTTPException(422,"Cette heure n’existe pas dans ce fuseau lors du changement d’heure.")
    if offset is None and len(choices)==1:
        return choices[0]['starts_at']
    for choice in choices:
        if choice['utc_offset_minutes']==offset:
            return choice['starts_at']
    raise HTTPException(422,'Choisissez le décalage UTC de cette heure pour lever toute ambiguïté.')

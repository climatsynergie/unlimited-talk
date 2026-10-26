"""Shared value validation without identity/session or storage dependencies."""
import re


def email_address(value):
    value = value.strip().lower()
    if len(value) > 254 or '..' in value or not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}', value):
        raise ValueError('Adresse courriel invalide')
    return value


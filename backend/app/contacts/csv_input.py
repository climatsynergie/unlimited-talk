"""Pure CSV validation, independent of transport, storage and task execution.

This module never changes contacts or their do-not-contact flags. The later
import worker must explicitly confirm a validated source and merge profiles in
an atomic, idempotent database transaction.
"""
import csv
from dataclasses import dataclass
import io
import unicodedata

import phonenumbers

from app.validation import email_address


class CsvInputError(ValueError):
    """Safe French validation message; never log uploaded source contents."""


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 10 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 100


FIELDS = {'phone', 'first_name', 'last_name', 'display_name', 'email',
          'address', 'city', 'province', 'postal_code'}
FIELD_LENGTHS = {'first_name': 120, 'last_name': 120, 'display_name': 240,
                 'email': 254, 'address': 500, 'city': 120, 'province': 120,
                 'postal_code': 32}
FIELD_NAMES = {'first_name': 'Prénom', 'last_name': 'Nom', 'display_name': 'Nom complet',
               'email': 'Courriel', 'address': 'Adresse', 'city': 'Ville',
               'province': 'Province', 'postal_code': 'Code postal'}
ALIASES = {
    'phone': {'telephone', 'tel', 'phone', 'phonenumber', 'numero', 'numerodetelephone'},
    'first_name': {'prenom', 'firstname'}, 'last_name': {'nom', 'lastname'},
    'display_name': {'nomcomplet', 'fullname', 'displayname'},
    'email': {'courriel', 'email', 'adressecourriel', 'adressemail'},
    'address': {'adresse', 'address'}, 'city': {'ville', 'city'},
    'province': {'province', 'state'}, 'postal_code': {'codepostal', 'postalcode', 'zipcode'},
}


@dataclass(frozen=True)
class ValidatedRow:
    row_number: int
    profile: dict[str, str]
    error: str | None = None
    warnings: tuple[str, ...] = ()
    duplicate_in_file: bool = False


@dataclass(frozen=True)
class ValidatedCsv:
    headers: tuple[str, ...]
    rows: tuple[ValidatedRow, ...]
    delimiter: str
    skipped_blank: int
    valid_count: int
    invalid_count: int
    distinct_count: int
    duplicate_count: int


def normalize_phone(value: str, region: str = 'CA') -> str:
    if region not in phonenumbers.SUPPORTED_REGIONS:
        raise CsvInputError('Le pays par défaut n’est pas reconnu.')
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise CsvInputError('Le numéro de téléphone est absent ou invalide.')
    try:
        number = phonenumbers.parse(value.strip(), region)
    except phonenumbers.NumberParseException:
        raise CsvInputError('Le numéro de téléphone n’est pas reconnu.') from None
    if number.extension:
        raise CsvInputError('Le numéro contient un poste interne : indiquez un numéro direct.')
    if not phonenumbers.is_possible_number(number) or not phonenumbers.is_valid_number(number):
        raise CsvInputError('Le numéro de téléphone n’est pas valide.')
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def _header_key(value):
    plain = unicodedata.normalize('NFKD', value)
    return ''.join(c.lower() for c in plain if c.isalnum() and not unicodedata.combining(c))


def suggest_mapping(headers: tuple[str, ...]) -> dict[str, str]:
    # Ambiguous alternatives must be chosen by the administrator, not guessed.
    result = {}
    for field_name, aliases in ALIASES.items():
        matches = [header for header in headers if _header_key(header) in aliases]
        if len(matches) == 1:
            result[field_name] = matches[0]
    return result


def _reader(source: bytes, delimiter: str | None, encoding: str, limits: Limits):
    if not source or len(source) > limits.max_bytes:
        raise CsvInputError('Le fichier est vide ou dépasse la taille autorisée.')
    if encoding not in {'utf-8-sig', 'cp1252'}:
        raise CsvInputError('Choisissez l’encodage UTF-8 ou Windows-1252.')
    try:
        text = source.decode(encoding)
    except UnicodeError:
        raise CsvInputError('L’encodage du fichier est invalide. Exportez en CSV UTF-8 ou choisissez Windows-1252.') from None
    if '\x00' in text:
        raise CsvInputError('Le fichier ne semble pas être un fichier CSV texte.')
    if delimiter is not None and delimiter not in {',', ';', '\t'}:
        raise CsvInputError('Choisissez la virgule, le point-virgule ou la tabulation comme séparateur.')
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=',;\t').delimiter
        except csv.Error:
            # A single-column telephone file is a valid input.
            first = text.splitlines()[0] if text.splitlines() else ''
            if not any(char in first for char in ',;\t'):
                delimiter = ','
            else:
                raise CsvInputError('Impossible de reconnaître le séparateur. Choisissez-le explicitement.') from None
    return csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True), delimiter


def validate_csv(source: bytes, mapping: dict[str, str], *, region: str = 'CA',
                 delimiter: str | None = None, encoding: str = 'utf-8-sig',
                 limits: Limits = Limits()) -> ValidatedCsv:
    reader, delimiter = _reader(source, delimiter, encoding, limits)
    try:
        headers = tuple(value.strip() for value in next(reader))
    except (StopIteration, csv.Error):
        raise CsvInputError('La ligne d’en-têtes CSV est absente ou invalide.') from None
    if not headers or len(headers) > limits.max_columns or any(not h or len(h) > 200 for h in headers):
        raise CsvInputError('Les en-têtes sont vides, trop longs ou trop nombreux.')
    if len({_header_key(h) for h in headers}) != len(headers):
        raise CsvInputError('Plusieurs colonnes portent le même nom. Renommez-les avant l’import.')
    if set(mapping) - FIELDS:
        raise CsvInputError('La correspondance contient un champ non autorisé.')
    if not mapping.get('phone') or any(value not in headers for value in mapping.values()):
        raise CsvInputError('Associez le téléphone et vérifiez les colonnes sélectionnées.')
    if len(set(mapping.values())) != len(mapping):
        raise CsvInputError('Chaque colonne source ne peut être associée qu’à un seul champ.')
    if region not in phonenumbers.SUPPORTED_REGIONS:
        raise CsvInputError('Le pays par défaut n’est pas reconnu.')
    indices = {key: headers.index(value) for key, value in mapping.items()}
    rows, seen = [], set()
    valid_count = invalid_count = duplicate_count = skipped_blank = 0
    try:
        for number, values in enumerate(reader, start=2):
            if number - 1 > limits.max_rows:
                raise CsvInputError('Le fichier dépasse le nombre de lignes autorisé.')
            if not any(value.strip() for value in values):
                skipped_blank += 1
                continue
            if len(values) != len(headers):
                rows.append(ValidatedRow(number, {}, 'Le nombre de valeurs ne correspond pas aux en-têtes.'))
                invalid_count += 1
                continue
            try:
                phone = normalize_phone(values[indices['phone']], region)
            except CsvInputError as error:
                rows.append(ValidatedRow(number, {}, str(error)))
                invalid_count += 1
                continue
            profile, warnings = {'phone': phone}, []
            for name, index in indices.items():
                if name == 'phone':
                    continue
                value = values[index].strip()
                if not value:
                    continue  # Blank values must never erase existing profile data.
                if len(value) > FIELD_LENGTHS[name]:
                    warnings.append(FIELD_NAMES[name] + ' trop long : champ ignoré.')
                    continue
                if name == 'email':
                    try:
                        value = email_address(value)
                    except ValueError:
                        warnings.append('Courriel invalide : champ ignoré, téléphone conservé.')
                        continue
                profile[name] = value
            if 'display_name' not in profile:
                display_name = ' '.join(profile[name] for name in ('first_name', 'last_name') if name in profile)
                if display_name and len(display_name) <= FIELD_LENGTHS['display_name']:
                    profile['display_name'] = display_name
                elif display_name:
                    warnings.append('Nom complet trop long : prénom et nom conservés séparément.')
            duplicate = phone in seen
            duplicate_count += int(duplicate)
            seen.add(phone)
            rows.append(ValidatedRow(number, profile, warnings=tuple(warnings), duplicate_in_file=duplicate))
            valid_count += 1
    except csv.Error:
        raise CsvInputError('Le CSV est mal formé. Vérifiez les guillemets et les séparateurs.') from None
    if not rows:
        raise CsvInputError('Le fichier ne contient aucune ligne de données.')
    return ValidatedCsv(headers, tuple(rows), delimiter, skipped_blank, valid_count,
                        invalid_count, len(seen), duplicate_count)

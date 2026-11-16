"""Versioned qualification snapshots in the existing immutable event streams.

Campaign events hold saved contact responses; each appointment keeps its own
validated snapshot. Editing a later qualification never rewrites an earlier RDV.
The indexed event projections are the source of truth, not free-text notes.
"""
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator
from app.identity.service import query

SCHEMAS = {version: json.loads(Path(__file__).with_name(f'qualification-v{version}.json').read_text())
           for version in (1, 2, 3)}
# The questions/versions stay immutable; current input policy is deliberately
# optional and free-form. Historical event snapshots are never rewritten.
SCHEMA = {**SCHEMAS[3], 'fields': [{**f, 'required': False, 'condition': None} for f in SCHEMAS[3]['fields']],
          'previous_versions': [SCHEMAS[2], SCHEMAS[1]]}
FIELDS = SCHEMA['fields']


class QualificationError(ValueError):
    """Only static field/reason identifiers; never retain submitted values."""
    def __init__(self, field, reason, message):
        self.field, self.reason = field, reason
        super().__init__(message)


def normalize(answers, *, schema_version=3, complete=False):
    fields = SCHEMAS[schema_version]['fields']
    if not isinstance(answers, dict) or set(answers) - {f['key'] for f in fields}:
        raise QualificationError(None, 'shape', 'Fiche de qualification invalide.')
    result = {}
    for field in fields:
        value = answers.get(field['key'], '')
        # JSONB cannot represent NUL. All ordinary text (including whitespace,
        # nonstandard choices and postal codes) is kept exactly as submitted.
        if not isinstance(value, str) or '\x00' in value:
            raise QualificationError(field['key'], 'text', 'Texte non pris en charge : ' + field['label'])
        result[field['key']] = value
    return result


class Qualification(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: int = Field(strict=True, ge=1, le=3)
    answers: dict[str, StrictStr] = Field(max_length=len(FIELDS))

    @model_validator(mode='after')
    def clean_answers(self):
        self.answers = normalize(self.answers, schema_version=self.schema_version)
        return self


def complete_snapshot(value):
    return {'schema_version': value.schema_version, 'answers': normalize(value.answers, schema_version=value.schema_version, complete=True)}


def is_complete(snapshot):
    try:
        complete_snapshot(Qualification.model_validate(snapshot))
        return True
    except ValueError:
        return False


def contact_snapshot(db, campaign_id, contact_id):
    row = query(db, '''SELECT id, details->'qualification' AS qualification
        FROM staging.campaign_events WHERE campaign_id=:campaign AND contact_id=:contact
        AND action='contact.qualification_saved' ORDER BY id DESC LIMIT 1''',
        campaign=campaign_id, contact=contact_id).mappings().first()
    return {'revision': str(row['id']), 'qualification': row['qualification']} if row else None


def save_contact_snapshot(db, user, campaign_id, contact_id, snapshot, *, request_id=None, request_hash=None):
    details = {'qualification': snapshot, 'complete': is_complete(snapshot)}
    identifier = query(db, '''INSERT INTO staging.campaign_events
        (campaign_id,contact_id,actor_id,action,details,request_id,request_hash)
        VALUES (:campaign,:contact,:actor,'contact.qualification_saved',CAST(:details AS jsonb),:request,:hash)
        RETURNING id''', campaign=campaign_id, contact=contact_id, actor=user['id'],
        details=json.dumps(details), request=request_id, hash=request_hash).scalar_one()
    return {'revision': str(identifier), 'qualification': snapshot}


def appointment_snapshot(db, identifier):
    return query(db, '''SELECT details->'after'->'qualification' FROM staging.appointment_events
        WHERE appointment_id=:id AND action IN ('appointment.created','appointment.updated')
        AND details->'after'->'qualification' IS NOT NULL ORDER BY id DESC LIMIT 1''', id=identifier).scalar_one_or_none()

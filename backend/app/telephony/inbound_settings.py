"""Administrative values; saving configuration never changes Twilio routing."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Hours(Body):
    weekday: StrictInt = Field(ge=0, le=6)
    start: StrictInt = Field(ge=0, le=1439)
    end: StrictInt = Field(ge=1, le=1440)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('La fin doit suivre le début sur la même journée.')
        return self


class Member(Body):
    user_id: UUID
    mode: Literal['mixed'] = 'mixed'


class Settings(Body):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(max_length=40)
    timezone: str = Field(default='America/Toronto', max_length=80)
    max_wait_seconds: StrictInt = Field(default=60, ge=10, le=600)
    offer_seconds: StrictInt = Field(default=20, ge=5, le=60)
    hours: list[Hours] = Field(default_factory=list, max_length=14)
    agents: list[Member] = Field(default_factory=list, max_length=20)
    is_active: StrictBool = True

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('Nom requis')
        return value.strip()

    @field_validator('phone')
    @classmethod
    def international(cls, value):
        value = re.sub(r'[ ().-]', '', value)
        if not re.fullmatch(r'\+[1-9][0-9]{8,14}', value):
            raise ValueError('Numéro international requis')
        return value

    @field_validator('timezone')
    @classmethod
    def zone(cls, value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError): raise ValueError('Fuseau invalide') from None
        return value

    @model_validator(mode='after')
    def consistent(self):
        if self.offer_seconds > self.max_wait_seconds:
            raise ValueError("La sonnerie dépasse l'attente maximale.")
        if len({a.user_id for a in self.agents}) != len(self.agents):
            raise ValueError('Agent attribué plusieurs fois.')
        windows = sorted(self.hours, key=lambda h: (h.weekday, h.start))
        for a, b in zip(windows, windows[1:]):
            if a.weekday == b.weekday and a.end > b.start:
                raise ValueError('Les plages horaires se chevauchent.')
        self.hours = windows
        self.agents = sorted(self.agents, key=lambda a: a.user_id.int)
        return self


class Create(Settings):
    id: UUID


class Update(Settings):
    request_id: UUID
    version: StrictInt = Field(ge=0)


def within_hours(hours, timezone, at: datetime):
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError('Instant avec fuseau requis')
    local = at.astimezone(ZoneInfo(timezone))
    minute = local.hour * 60 + local.minute
    return any(h['weekday'] == local.weekday() and h['start'] <= minute < h['end'] for h in hours)

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, Field, model_validator, field_validator, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Preferences(StrictModel):
    mode: Literal['demo', 'tuya'] = 'demo'
    tariff: float = Field(default=29.5, ge=0, le=100000)
    start_w: float = Field(default=5, gt=0, le=100000)
    start_hold_s: int = Field(default=5, ge=0, le=3600)
    end_w: float = Field(default=2, ge=0, le=100000)
    hold_s: int = Field(default=30, ge=5, le=3600)
    timezone: str = 'Asia/Almaty'
    notifications: bool = True

    @field_validator('timezone')
    @classmethod
    def check_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Неизвестный часовой пояс IANA')
        return value

    @model_validator(mode='after')
    def thresholds(self):
        if self.end_w >= self.start_w:
            raise ValueError('Порог завершения должен быть ниже порога начала')
        return self


class RelayBody(StrictModel):
    on: bool


class DemoBody(StrictModel):
    action: Literal['charge', 'finish', 'disconnect', 'reconnect']


class RuleBody(StrictModel):
    device_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['timer', 'low_power', 'schedule', 'night', 'max_duration']
    enabled: bool = True
    minutes: int = Field(default=60, ge=1, le=10080)
    threshold: float = Field(default=3, ge=0, le=100000)
    hold_s: int = Field(default=60, ge=5, le=3600)
    start: str = Field(default='23:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    end: str = Field(default='07:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')

    @model_validator(mode='after')
    def distinct_times(self):
        if self.kind in ('schedule', 'night') and self.start == self.end:
            raise ValueError('Начало и конец должны отличаться')
        return self


class RuleToggle(StrictModel):
    enabled: bool


class MappingBody(StrictModel):
    switch: str | None = None
    power: str | None = None
    voltage: str | None = None
    current: str | None = None
    energy: str | None = None


class LoginBody(StrictModel):
    password: str = Field(max_length=512)


class ActivateBody(StrictModel):
    device_id: str = Field(min_length=1, max_length=100)


class TestRelayBody(RelayBody):
    confirmed: Literal[True]

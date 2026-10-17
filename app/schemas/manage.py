"""Schemas da area do dono (configuracao do negocio)."""

import re
from datetime import date, datetime, time
from typing import Any, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.constants import TIME_STEP_MINUTES


def _step(value: int | None, name: str) -> int | None:
    if value is not None and value % TIME_STEP_MINUTES != 0:
        raise ValueError(f"{name} deve ser multiplo de {TIME_STEP_MINUTES} minutos")
    return value


# ---------- recursos e servicos ----------


class ResourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class ResourceAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    is_active: bool


class ServiceFields(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    duration_minutes: int = Field(gt=0, le=1440)
    buffer_minutes: int = Field(default=0, ge=0, le=1440)
    capacity: int = Field(default=1, ge=1, le=500)
    slot_interval_minutes: int | None = Field(
        default=None,
        ge=0,
        le=1440,
        description="Distancia entre inicios. 0 ou vazio = igual a duracao.",
    )
    price_cents: int | None = Field(default=None, ge=0)
    is_active: bool = True

    @field_validator("duration_minutes")
    @classmethod
    def _duration(cls, v: int) -> int:
        return _step(v, "duration_minutes")  # type: ignore[return-value]

    @field_validator("buffer_minutes")
    @classmethod
    def _buffer(cls, v: int) -> int:
        return _step(v, "buffer_minutes")  # type: ignore[return-value]

    @field_validator("slot_interval_minutes")
    @classmethod
    def _interval(cls, v: int | None) -> int | None:
        return _step(v, "slot_interval_minutes")


class ServiceIn(ServiceFields):
    resource_ids: list[UUID] | None = Field(
        default=None, description="Profissionais que atendem. Vazio = todos."
    )


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    duration_minutes: int | None = Field(default=None, gt=0, le=1440)
    buffer_minutes: int | None = Field(default=None, ge=0, le=1440)
    capacity: int | None = Field(default=None, ge=1, le=500)
    slot_interval_minutes: int | None = Field(default=None, ge=0, le=1440)
    price_cents: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    resource_ids: list[UUID] | None = None

    @field_validator("duration_minutes", "buffer_minutes", "slot_interval_minutes")
    @classmethod
    def _steps(cls, v: int | None) -> int | None:
        return _step(v, "valor")


class ServiceAdminOut(ServiceFields):
    id: UUID
    resource_ids: list[UUID]


# ---------- horarios ----------


class WeeklyRuleIn(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 = segunda ... 6 = domingo")
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("end_time deve ser maior que start_time")
        return self


class WeeklyRulesIn(BaseModel):
    rules: list[WeeklyRuleIn] = Field(max_length=100)


class WeeklyRuleOut(WeeklyRuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    resource_id: UUID


class DateExceptionIn(BaseModel):
    date: date
    kind: Literal["closed", "custom_hours"]
    resource_id: UUID | None = None
    start_time: time | None = None
    end_time: time | None = None
    reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _times(self) -> Self:
        if self.kind == "custom_hours":
            if not self.start_time or not self.end_time or self.end_time <= self.start_time:
                raise ValueError("custom_hours exige start_time e end_time (fim maior que inicio)")
        elif self.start_time or self.end_time:
            raise ValueError("closed nao usa horarios")
        return self


class DateExceptionOut(DateExceptionIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class BlockIn(BaseModel):
    start_at: AwareDatetime
    end_at: AwareDatetime
    resource_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.end_at <= self.start_at:
            raise ValueError("end_at deve ser maior que start_at")
        return self


class BlockOut(BlockIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


# ---------- configuracoes do negocio ----------

FormField = Literal["name", "phone", "email", "notes", "resource_id", "consent_lgpd"]


class CustomField(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    type: Literal["text", "number", "select"] = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _select(self) -> Self:
        if self.type == "select" and not self.options:
            raise ValueError("select exige options")
        return self


class FormConfig(BaseModel):
    required_fields: list[FormField] = Field(default_factory=lambda: ["name", "phone"])
    optional_fields: list[FormField] = Field(default_factory=lambda: ["email", "notes"])
    custom_fields: list[CustomField] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        keys = [f.key for f in self.custom_fields]
        if len(keys) != len(set(keys)):
            raise ValueError("custom_fields com chave repetida")
        return self


class SettingsOut(BaseModel):
    name: str
    slug: str
    timezone: str
    availability_mode: Literal["rules", "open_dates"]
    auto_confirm: bool
    min_notice_minutes: int
    max_advance_days: int
    allowed_origins: list[str]
    form_config: dict[str, Any]


class SettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = None
    availability_mode: Literal["rules", "open_dates"] | None = None
    auto_confirm: bool | None = None
    min_notice_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    max_advance_days: int | None = Field(default=None, ge=1, le=365)
    allowed_origins: list[str] | None = Field(default=None, max_length=50)
    form_config: FormConfig | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("fuso horario invalido") from None
        return v

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned = []
        for origin in v:
            origin = origin.strip().rstrip("/")
            if not re.match(r"^https?://[^/\s]+$", origin):
                raise ValueError(f"origem invalida: {origin} (use https://dominio.com.br)")
            cleaned.append(origin)
        return cleaned


# ---------- agendamentos (visao do dono) ----------


class AdminBookingOut(BaseModel):
    id: UUID
    status: str
    service_id: UUID
    service_name: str
    resource_id: UUID
    resource_name: str
    start: datetime
    end: datetime
    price_cents: int | None
    customer_name: str
    customer_phone: str
    customer_email: str | None
    notes: str | None
    custom_data: dict[str, Any]
    cancel_reason: str | None
    created_at: datetime


class RescheduleIn(BaseModel):
    start_at: AwareDatetime
    resource_id: UUID | None = None


class AdminCancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)

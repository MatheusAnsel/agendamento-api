from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class TenantConfigOut(BaseModel):
    name: str
    slug: str
    timezone: str
    availability_mode: str
    min_notice_minutes: int
    max_advance_days: int
    form_config: dict[str, Any]


class ResourceOut(BaseModel):
    id: UUID
    name: str


class ServiceOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    duration_minutes: int
    capacity: int
    price_cents: int | None
    resource_ids: list[UUID]


class SlotOut(BaseModel):
    start: datetime  # no fuso do negocio, com deslocamento (ex.: 2026-10-20T09:00:00-03:00)
    end: datetime
    resource_ids: list[UUID]
    remaining: int


class SlotsOut(BaseModel):
    service_id: UUID
    date: date
    timezone: str
    slots: list[SlotOut]


class AvailabilityOut(BaseModel):
    service_id: UUID
    timezone: str
    days: list[date]

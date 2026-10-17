from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=24)
    email: str | None = Field(default=None, max_length=254)


class BookingCreateIn(BaseModel):
    service_id: UUID
    start_at: AwareDatetime  # precisa trazer o fuso, ex.: 2026-10-20T14:00:00-03:00
    resource_id: UUID | None = None
    customer: CustomerIn
    custom: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=500)
    consent_lgpd: bool = False
    website: str | None = Field(default=None, description="Campo isca contra robos: deixe vazio")


class BookingCancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class BookingOut(BaseModel):
    id: UUID
    token: str
    status: str
    service_id: UUID
    service_name: str
    resource_id: UUID
    resource_name: str
    start: datetime
    end: datetime
    price_cents: int | None
    customer_name: str
    created_at: datetime
    cancelled_at: datetime | None

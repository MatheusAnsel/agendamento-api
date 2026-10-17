from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    tenant_slug: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # segundos


class MeOut(BaseModel):
    id: UUID
    email: str
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str


class ApiKeyCreateIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedOut(ApiKeyOut):
    key: str  # chave completa, exibida uma unica vez

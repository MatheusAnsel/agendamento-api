import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

AVAILABILITY_MODES = ("rules", "open_dates")

DEFAULT_FORM_CONFIG: dict[str, Any] = {
    "required_fields": ["name", "phone"],
    "optional_fields": ["email", "notes"],
    "custom_fields": [],
}


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Um negocio/site atendido pela API. Todas as demais tabelas filtram por tenant_id."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("availability_mode IN ('rules', 'open_dates')", name="availability_mode"),
        CheckConstraint("min_notice_minutes >= 0", name="min_notice_non_negative"),
        CheckConstraint("max_advance_days > 0", name="max_advance_positive"),
        UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="America/Sao_Paulo"
    )
    # 'rules': horarios gerados pela regra semanal. 'open_dates': so existem horarios
    # nos dias que o dono publicou manualmente (date_exceptions do tipo custom_hours).
    availability_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="rules"
    )
    auto_confirm: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    min_notice_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    max_advance_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    allowed_origins: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    form_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: dict(DEFAULT_FORM_CONFIG),
        server_default=text(f"'{json.dumps(DEFAULT_FORM_CONFIG)}'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class ApiKey(UUIDPrimaryKeyMixin, Base):
    """Chave publica usada pelos front ends. Guarda apenas o hash (SHA-256)."""

    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False, server_default="default")
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Dono (ou equipe) do tenant, autenticado com e-mail e senha para gerar o JWT."""

    __tablename__ = "admin_users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_admin_users_tenant_email"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

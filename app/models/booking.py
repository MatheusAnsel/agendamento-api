import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

BOOKING_STATUSES = ("pendente", "confirmado", "concluido", "cancelado", "nao_compareceu")


def new_booking_token() -> str:
    return secrets.token_urlsafe(24)


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cliente final do tenant, unico por telefone (formato E.164)."""

    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("tenant_id", "phone", name="uq_customers_tenant_phone"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    consent_lgpd_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Booking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Agendamento.

    Intervalo ocupado = [start_at, occupied_until), onde occupied_until = fim do servico +
    buffer, calculado pelo backend. end_at e o fim do atendimento em si.

    Servicos de capacidade 1 (is_exclusive = true) sao protegidos pela constraint de exclusao
    do PostgreSQL: dois agendamentos ativos do mesmo recurso nao podem se sobrepor, mesmo com
    requisicoes simultaneas. Servicos com capacidade maior (aulas, turmas) nao usam a
    constraint e a lotacao e controlada na aplicacao, sob lock.
    """

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pendente', 'confirmado', 'concluido', 'cancelado', 'nao_compareceu')",
            name="status",
        ),
        CheckConstraint("end_at > start_at", name="end_after_start"),
        CheckConstraint("occupied_until >= end_at", name="occupied_covers_end"),
        UniqueConstraint("token", name="uq_bookings_token"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_bookings_tenant_idempotency"),
        ExcludeConstraint(
            ("resource_id", "="),
            (text("tstzrange(start_at, occupied_until, '[)')"), "&&"),
            using="gist",
            where=text("is_exclusive AND status <> 'cancelado'"),
            name="ex_bookings_no_overlap",
        ),
        Index("ix_bookings_tenant_start", "tenant_id", "start_at"),
        Index("ix_bookings_resource_start", "resource_id", "start_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occupied_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_exclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pendente")
    # Valores recalculados pelo backend a partir do servico no momento da reserva.
    price_cents: Mapped[int | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Token de consulta/cancelamento pelo cliente, sem precisar de conta.
    token: Mapped[str] = mapped_column(String(64), nullable=False, default=new_booking_token)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

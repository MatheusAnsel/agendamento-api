import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import TIME_STEP_MINUTES
from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Resource(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Quem (ou o que) atende: barbeiro, sala, mecanico. Todo tenant tem ao menos um."""

    __tablename__ = "resources"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Service(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint("buffer_minutes >= 0", name="buffer_non_negative"),
        CheckConstraint("capacity >= 1", name="capacity_positive"),
        CheckConstraint("price_cents IS NULL OR price_cents >= 0", name="price_non_negative"),
        CheckConstraint(
            "slot_interval_minutes IS NULL OR slot_interval_minutes >= 0",
            name="slot_interval_non_negative",
        ),
        # Duracao, intervalo entre inicios e buffer sao sempre multiplos de TIME_STEP_MINUTES.
        CheckConstraint(f"mod(duration_minutes, {TIME_STEP_MINUTES}) = 0", name="duration_step"),
        CheckConstraint(f"mod(buffer_minutes, {TIME_STEP_MINUTES}) = 0", name="buffer_step"),
        CheckConstraint(
            f"slot_interval_minutes IS NULL OR mod(slot_interval_minutes, {TIME_STEP_MINUTES}) = 0",
            name="slot_interval_step",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Intervalo apos o atendimento, durante o qual o recurso fica ocupado.
    buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # 1 = atendimento individual. Maior que 1 = aulas/turmas (varias pessoas no mesmo horario).
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Distancia entre os inicios dos horarios oferecidos. Nulo ou 0 = igual a duracao do servico
    # (um atendimento logo apos o outro, sem folga).
    slot_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


# Quais recursos podem executar cada servico.
service_resources = Table(
    "service_resources",
    Base.metadata,
    Column(
        "service_id",
        UUID(as_uuid=True),
        ForeignKey("services.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "resource_id",
        UUID(as_uuid=True),
        ForeignKey("resources.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

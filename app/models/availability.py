import uuid
from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, SmallInteger, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

EXCEPTION_KINDS = ("closed", "custom_hours")


class WeeklyRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Horario semanal recorrente de um recurso, interpretado no fuso do tenant.

    weekday segue o padrao do Python: 0 = segunda, 6 = domingo.
    Varios intervalos no mesmo dia (ex.: 09-12 e 14-18) sao varias linhas.
    """

    __tablename__ = "weekly_rules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="end_after_start"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)


class DateException(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Excecao para uma data especifica (hora local do tenant).

    - kind = 'closed': o dia inteiro fica fechado (feriado, folga).
    - kind = 'custom_hours': o dia usa estes intervalos no lugar da regra semanal
      (varias linhas na mesma data = varios intervalos). No modo 'open_dates' do tenant,
      sao estas linhas que abrem os dias.
    resource_id nulo vale para todos os recursos do tenant.
    """

    __tablename__ = "date_exceptions"
    __table_args__ = (
        CheckConstraint("kind IN ('closed', 'custom_hours')", name="kind"),
        CheckConstraint(
            "(kind = 'closed' AND start_time IS NULL AND end_time IS NULL) OR "
            "(kind = 'custom_hours' AND start_time IS NOT NULL AND end_time IS NOT NULL "
            "AND end_time > start_time)",
            name="times_match_kind",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Block(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bloqueio pontual de um intervalo (consulta medica, almoco fora).

    resource_id nulo bloqueia todos os recursos do tenant.
    """

    __tablename__ = "blocks"
    __table_args__ = (CheckConstraint("end_at > start_at", name="end_after_start"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

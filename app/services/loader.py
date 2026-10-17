"""Carrega do banco o que o motor de horarios precisa (o motor em si nao acessa o banco)."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Block,
    Booking,
    DateException,
    Resource,
    Service,
    Tenant,
    WeeklyRule,
    service_resources,
)
from app.services.slots import (
    BlockSpec,
    BookingSpec,
    DateExceptionSpec,
    ServiceSpec,
    SlotContext,
    TenantRules,
    WeeklyWindow,
)


def tenant_rules(tenant: Tenant) -> TenantRules:
    return TenantRules(
        timezone=ZoneInfo(tenant.timezone),
        availability_mode=tenant.availability_mode,
        min_notice_minutes=tenant.min_notice_minutes,
        max_advance_days=tenant.max_advance_days,
    )


def service_spec(service: Service) -> ServiceSpec:
    return ServiceSpec(
        id=service.id,
        duration_minutes=service.duration_minutes,
        buffer_minutes=service.buffer_minutes,
        capacity=service.capacity,
        slot_interval_minutes=service.slot_interval_minutes,
    )


async def get_active_service(
    session: AsyncSession, tenant_id: UUID, service_id: UUID
) -> Service | None:
    return (
        await session.execute(
            select(Service).where(
                Service.id == service_id,
                Service.tenant_id == tenant_id,
                Service.is_active.is_(True),
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def resource_ids_for_service(
    session: AsyncSession, tenant_id: UUID, service_id: UUID
) -> list[UUID]:
    """Recursos ativos que atendem o servico. Sem vinculo explicito, todos os recursos ativos."""
    active = (
        select(Resource.id)
        .where(
            Resource.tenant_id == tenant_id,
            Resource.is_active.is_(True),
            Resource.deleted_at.is_(None),
        )
        .order_by(Resource.created_at, Resource.id)
    )
    linked = set(
        (
            await session.execute(
                select(service_resources.c.resource_id).where(
                    service_resources.c.service_id == service_id
                )
            )
        ).scalars()
    )
    ids = list((await session.execute(active)).scalars())
    return [i for i in ids if i in linked] if linked else ids


async def build_context(
    session: AsyncSession,
    tenant: Tenant,
    service: Service,
    resource_ids: Sequence[UUID],
    first_day: date,
    last_day: date,
    now: datetime | None = None,
) -> SlotContext:
    """Monta o contexto do motor para o intervalo de datas locais [first_day, last_day]."""
    rules = tenant_rules(tenant)
    tz = rules.timezone
    # Folga de um dia para cada lado: cobre fuso e reservas que atravessam a meia-noite.
    lo = datetime.combine(first_day, time.min, tzinfo=tz).astimezone(UTC) - timedelta(days=1)
    hi = datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=tz).astimezone(
        UTC
    ) + timedelta(days=1)

    weekly = (
        await session.execute(
            select(WeeklyRule).where(
                WeeklyRule.tenant_id == tenant.id, WeeklyRule.resource_id.in_(resource_ids)
            )
        )
    ).scalars()
    exceptions = (
        await session.execute(
            select(DateException).where(
                DateException.tenant_id == tenant.id,
                DateException.date.between(first_day - timedelta(days=1), last_day),
                or_(
                    DateException.resource_id.is_(None),
                    DateException.resource_id.in_(resource_ids),
                ),
            )
        )
    ).scalars()
    blocks = (
        await session.execute(
            select(Block).where(
                Block.tenant_id == tenant.id,
                Block.start_at < hi,
                Block.end_at > lo,
                or_(Block.resource_id.is_(None), Block.resource_id.in_(resource_ids)),
            )
        )
    ).scalars()
    bookings = (
        await session.execute(
            select(Booking).where(
                Booking.tenant_id == tenant.id,
                Booking.resource_id.in_(resource_ids),
                Booking.status != "cancelado",
                Booking.start_at < hi,
                Booking.occupied_until > lo,
            )
        )
    ).scalars()

    return SlotContext(
        tenant=rules,
        service=service_spec(service),
        now=now or datetime.now(UTC),
        weekly=[WeeklyWindow(w.resource_id, w.weekday, w.start_time, w.end_time) for w in weekly],
        exceptions=[
            DateExceptionSpec(e.resource_id, e.date, e.kind, e.start_time, e.end_time)
            for e in exceptions
        ],
        blocks=[BlockSpec(b.resource_id, b.start_at, b.end_at) for b in blocks],
        bookings=[
            BookingSpec(
                b.resource_id, b.service_id, b.start_at, b.occupied_until, b.is_exclusive, b.status
            )
            for b in bookings
        ],
    )

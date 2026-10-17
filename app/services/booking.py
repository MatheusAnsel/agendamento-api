"""Regras de criacao, cancelamento e remarcacao de agendamentos."""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Booking, Customer, Resource, Service, Tenant
from app.schemas.booking import BookingCreateIn, BookingOut
from app.services.forms import validate_form
from app.services.loader import (
    build_context,
    get_active_service,
    resource_ids_for_service,
)
from app.services.slots import ServiceSlot, slots_for_service

ACTIVE_STATUSES = ("pendente", "confirmado")
MAX_ACTIVE_BOOKINGS_PER_CUSTOMER = 3


def unavailable() -> AppError:
    return AppError(409, "slot_unavailable", "Horario indisponivel")


async def booking_out(session: AsyncSession, booking: Booking, tenant: Tenant) -> BookingOut:
    service = await session.get(Service, booking.service_id)
    resource = await session.get(Resource, booking.resource_id)
    customer = await session.get(Customer, booking.customer_id)
    assert service and resource and customer
    tz = ZoneInfo(tenant.timezone)
    return BookingOut(
        id=booking.id,
        token=booking.token,
        status=booking.status,
        service_id=service.id,
        service_name=service.name,
        resource_id=resource.id,
        resource_name=resource.name,
        start=booking.start_at.astimezone(tz),
        end=booking.end_at.astimezone(tz),
        price_cents=booking.price_cents,
        customer_name=customer.name,
        created_at=booking.created_at,
        cancelled_at=booking.cancelled_at,
    )


async def find_free_slot(
    session: AsyncSession,
    tenant: Tenant,
    service: Service,
    start_at: datetime,
    resource_id: UUID | None,
    *,
    now: datetime | None = None,
    exclude_booking_id: UUID | None = None,
) -> tuple[ServiceSlot, UUID]:
    """Confere se start_at e um horario livre do servico e escolhe o recurso."""
    tz = ZoneInfo(tenant.timezone)
    day = start_at.astimezone(tz).date()
    resource_ids = await resource_ids_for_service(session, tenant.id, service.id)
    if resource_id is not None and resource_id not in resource_ids:
        raise AppError(404, "resource_not_found", "Profissional nao atende este servico")
    ctx = await build_context(
        session, tenant, service, resource_ids, day, day, now, exclude_booking_id
    )
    for slot in slots_for_service(ctx, day, resource_ids):
        if slot.start == start_at:
            if resource_id is None:
                return slot, slot.default_resource_id
            if resource_id in slot.resource_ids:
                return slot, resource_id
            break
    raise unavailable()


async def _existing_by_key(session: AsyncSession, tenant_id: UUID, key: str) -> Booking | None:
    return (
        await session.execute(
            select(Booking).where(Booking.tenant_id == tenant_id, Booking.idempotency_key == key)
        )
    ).scalar_one_or_none()


async def create_booking(
    session: AsyncSession,
    tenant: Tenant,
    data: BookingCreateIn,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> tuple[Booking, bool]:
    """Cria o agendamento. Devolve (agendamento, criado). Repetir a chave devolve o original."""
    now = now or datetime.now(UTC)
    if idempotency_key and (
        existing := await _existing_by_key(session, tenant.id, idempotency_key)
    ):
        return existing, False

    service = await get_active_service(session, tenant.id, data.service_id)
    if service is None:
        raise AppError(404, "service_not_found", "Servico nao encontrado")

    form = validate_form(
        tenant.form_config,
        name=data.customer.name,
        phone=data.customer.phone,
        email=data.customer.email,
        notes=data.notes,
        custom=data.custom,
        has_resource_choice=data.resource_id is not None,
        consent_lgpd=data.consent_lgpd,
    )

    # Serializa as reservas do mesmo servico: a conferencia de horario e de lotacao
    # (turmas) acontece depois do lock. A constraint do banco continua sendo a garantia final
    # contra sobreposicao em um mesmo recurso, mesmo entre servicos diferentes.
    await session.execute(select(Service.id).where(Service.id == service.id).with_for_update())

    slot, resource_id = await find_free_slot(
        session, tenant, service, data.start_at, data.resource_id, now=now
    )

    customer = (
        await session.execute(
            select(Customer).where(Customer.tenant_id == tenant.id, Customer.phone == form["phone"])
        )
    ).scalar_one_or_none()
    if customer is None:
        customer = Customer(tenant_id=tenant.id, name=form["name"], phone=form["phone"])
        session.add(customer)
    customer.name = form["name"]
    if form["email"]:
        customer.email = form["email"]
    if data.consent_lgpd and customer.consent_lgpd_at is None:
        customer.consent_lgpd_at = now
    await session.flush()

    active = await session.scalar(
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.customer_id == customer.id,
            Booking.status.in_(ACTIVE_STATUSES),
            Booking.start_at > now,
        )
    )
    if (active or 0) >= MAX_ACTIVE_BOOKINGS_PER_CUSTOMER:
        raise AppError(
            409,
            "too_many_active_bookings",
            "Limite de agendamentos ativos atingido para este telefone",
        )

    booking = Booking(
        tenant_id=tenant.id,
        resource_id=resource_id,
        service_id=service.id,
        customer_id=customer.id,
        start_at=slot.start,
        end_at=slot.end,
        occupied_until=slot.end + timedelta(minutes=service.buffer_minutes),
        is_exclusive=service.capacity == 1,
        status="confirmado" if tenant.auto_confirm else "pendente",
        price_cents=service.price_cents,
        notes=form["notes"],
        custom_data=form["custom"],
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(booking)
            await session.flush()
    except IntegrityError:
        if idempotency_key and (
            existing := await _existing_by_key(session, tenant.id, idempotency_key)
        ):
            return existing, False
        raise unavailable() from None

    await session.commit()
    return booking, True


async def get_booking_by_token(session: AsyncSession, tenant_id: UUID, token: str) -> Booking:
    booking = (
        await session.execute(
            select(Booking).where(Booking.tenant_id == tenant_id, Booking.token == token)
        )
    ).scalar_one_or_none()
    if booking is None:
        raise AppError(404, "booking_not_found", "Agendamento nao encontrado")
    return booking


async def cancel_booking(
    session: AsyncSession,
    booking: Booking,
    reason: str | None,
    *,
    now: datetime | None = None,
    allow_past: bool = False,
) -> Booking:
    now = now or datetime.now(UTC)
    if booking.status not in ACTIVE_STATUSES:
        raise AppError(409, "not_cancellable", "Este agendamento nao pode mais ser cancelado")
    if not allow_past and booking.start_at <= now:
        raise AppError(409, "already_started", "O horario deste agendamento ja passou")
    booking.status = "cancelado"
    booking.cancelled_at = now
    booking.cancel_reason = reason
    await session.commit()
    return booking

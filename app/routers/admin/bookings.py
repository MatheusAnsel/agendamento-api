from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.deps import CurrentAdmin, SessionDep
from app.models import BOOKING_STATUSES, Booking, Customer, Resource, Service, Tenant
from app.schemas.manage import AdminBookingOut, AdminCancelIn, RescheduleIn
from app.services.booking import ACTIVE_STATUSES, cancel_booking, find_free_slot, unavailable

router = APIRouter(prefix="/v1/admin/bookings", tags=["admin"])


async def _out(session: AsyncSession, tenant: Tenant, b: Booking) -> AdminBookingOut:
    service = await session.get(Service, b.service_id)
    resource = await session.get(Resource, b.resource_id)
    customer = await session.get(Customer, b.customer_id)
    assert service and resource and customer
    tz = ZoneInfo(tenant.timezone)
    return AdminBookingOut(
        id=b.id,
        status=b.status,
        service_id=service.id,
        service_name=service.name,
        resource_id=resource.id,
        resource_name=resource.name,
        start=b.start_at.astimezone(tz),
        end=b.end_at.astimezone(tz),
        price_cents=b.price_cents,
        customer_name=customer.name,
        customer_phone=customer.phone,
        customer_email=customer.email,
        notes=b.notes,
        custom_data=b.custom_data,
        cancel_reason=b.cancel_reason,
        created_at=b.created_at,
    )


async def _load(session: AsyncSession, tenant_id: UUID, booking_id: UUID) -> Booking:
    booking = await session.get(Booking, booking_id)
    if booking is None or booking.tenant_id != tenant_id:
        raise AppError(404, "booking_not_found", "Agendamento nao encontrado")
    return booking


async def _tenant(session: AsyncSession, admin: CurrentAdmin) -> Tenant:
    tenant = await session.get(Tenant, admin.tenant_id)
    assert tenant is not None
    return tenant


@router.get("", response_model=list[AdminBookingOut])
async def list_bookings(
    admin: CurrentAdmin,
    session: SessionDep,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    resource_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AdminBookingOut]:
    """Agendamentos do negocio, do mais proximo ao mais distante. Datas no fuso do negocio."""
    tenant = await _tenant(session, admin)
    tz = ZoneInfo(tenant.timezone)
    query = select(Booking).where(Booking.tenant_id == tenant.id)
    if status:
        if status not in BOOKING_STATUSES:
            raise AppError(422, "invalid_status", "Status invalido")
        query = query.where(Booking.status == status)
    if date_from:
        query = query.where(
            Booking.start_at >= datetime.combine(date_from, time.min, tzinfo=tz).astimezone(UTC)
        )
    if date_to:
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
        query = query.where(Booking.start_at < end.astimezone(UTC))
    if resource_id:
        query = query.where(Booking.resource_id == resource_id)
    rows = (
        await session.execute(query.order_by(Booking.start_at).limit(limit).offset(offset))
    ).scalars()
    return [await _out(session, tenant, b) for b in rows]


@router.get("/{booking_id}", response_model=AdminBookingOut)
async def get_booking(
    booking_id: UUID, admin: CurrentAdmin, session: SessionDep
) -> AdminBookingOut:
    tenant = await _tenant(session, admin)
    return await _out(session, tenant, await _load(session, tenant.id, booking_id))


async def _transition(
    session: AsyncSession,
    admin: CurrentAdmin,
    booking_id: UUID,
    allowed_from: tuple[str, ...],
    new_status: str,
) -> AdminBookingOut:
    tenant = await _tenant(session, admin)
    booking = await _load(session, tenant.id, booking_id)
    if booking.status not in allowed_from:
        raise AppError(
            409,
            "invalid_transition",
            f"Nao e possivel passar de '{booking.status}' para '{new_status}'",
        )
    booking.status = new_status
    await session.commit()
    return await _out(session, tenant, booking)


@router.post("/{booking_id}/confirm", response_model=AdminBookingOut)
async def confirm(booking_id: UUID, admin: CurrentAdmin, session: SessionDep) -> AdminBookingOut:
    return await _transition(session, admin, booking_id, ("pendente",), "confirmado")


@router.post("/{booking_id}/complete", response_model=AdminBookingOut)
async def complete(booking_id: UUID, admin: CurrentAdmin, session: SessionDep) -> AdminBookingOut:
    return await _transition(session, admin, booking_id, ("confirmado",), "concluido")


@router.post("/{booking_id}/no-show", response_model=AdminBookingOut)
async def no_show(booking_id: UUID, admin: CurrentAdmin, session: SessionDep) -> AdminBookingOut:
    return await _transition(session, admin, booking_id, ("confirmado",), "nao_compareceu")


@router.post("/{booking_id}/cancel", response_model=AdminBookingOut)
async def cancel(
    booking_id: UUID,
    admin: CurrentAdmin,
    session: SessionDep,
    data: AdminCancelIn | None = None,
) -> AdminBookingOut:
    tenant = await _tenant(session, admin)
    booking = await _load(session, tenant.id, booking_id)
    await cancel_booking(session, booking, data.reason if data else None, allow_past=True)
    return await _out(session, tenant, booking)


@router.post("/{booking_id}/reschedule", response_model=AdminBookingOut)
async def reschedule(
    booking_id: UUID, data: RescheduleIn, admin: CurrentAdmin, session: SessionDep
) -> AdminBookingOut:
    """Muda o horario (e, opcionalmente, o profissional) conferindo a agenda livre."""
    tenant = await _tenant(session, admin)
    booking = await _load(session, tenant.id, booking_id)
    if booking.status not in ACTIVE_STATUSES:
        raise AppError(409, "not_reschedulable", "Este agendamento nao pode ser remarcado")
    service = await session.get(Service, booking.service_id)
    assert service
    await session.execute(select(Service.id).where(Service.id == service.id).with_for_update())
    slot, resource_id = await find_free_slot(
        session,
        tenant,
        service,
        data.start_at,
        data.resource_id or booking.resource_id,
        exclude_booking_id=booking.id,
    )
    booking.resource_id = resource_id
    booking.start_at = slot.start
    booking.end_at = slot.end
    booking.occupied_until = slot.end + timedelta(minutes=service.buffer_minutes)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise unavailable() from None
    await session.commit()
    return await _out(session, tenant, booking)

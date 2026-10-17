from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status

from app.core.errors import AppError
from app.core.ratelimit import rate_limit
from app.deps import CurrentTenant, SessionDep
from app.schemas.booking import BookingCancelIn, BookingCreateIn, BookingOut
from app.services.booking import (
    booking_out,
    cancel_booking,
    create_booking,
    get_booking_by_token,
)

router = APIRouter(prefix="/v1/bookings", tags=["publico"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=80)]


@router.post(
    "",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("bookings", "rate_limit_bookings_per_minute"))],
)
async def create(
    data: BookingCreateIn,
    response: Response,
    tenant: CurrentTenant,
    session: SessionDep,
    idempotency_key: IdempotencyKey = None,
) -> BookingOut:
    """Cria um agendamento. Repetir a mesma Idempotency-Key devolve o agendamento original (200)."""
    if data.website:
        raise AppError(400, "rejected", "Requisicao rejeitada")
    booking, created = await create_booking(session, tenant, data, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return await booking_out(session, booking, tenant)


@router.get("/{token}", response_model=BookingOut)
async def get_one(token: str, tenant: CurrentTenant, session: SessionDep) -> BookingOut:
    booking = await get_booking_by_token(session, tenant.id, token)
    return await booking_out(session, booking, tenant)


@router.post("/{token}/cancel", response_model=BookingOut)
async def cancel(
    token: str,
    tenant: CurrentTenant,
    session: SessionDep,
    data: BookingCancelIn | None = None,
) -> BookingOut:
    booking = await get_booking_by_token(session, tenant.id, token)
    await cancel_booking(session, booking, data.reason if data else None)
    return await booking_out(session, booking, tenant)

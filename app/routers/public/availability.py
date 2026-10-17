from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.deps import CurrentTenant, SessionDep
from app.schemas.public import AvailabilityOut, SlotOut, SlotsOut
from app.services.loader import build_context, get_active_service, resource_ids_for_service
from app.services.slots import available_days, slots_for_service

router = APIRouter(prefix="/v1", tags=["publico"])

MAX_AVAILABILITY_DAYS = 62


async def _resolve(
    session: SessionDep, tenant_id: UUID, service_id: UUID, resource_id: UUID | None
):
    service = await get_active_service(session, tenant_id, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servico nao encontrado")
    resource_ids = await resource_ids_for_service(session, tenant_id, service_id)
    if resource_id is not None:
        if resource_id not in resource_ids:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Recurso nao atende este servico")
        resource_ids = [resource_id]
    return service, resource_ids


@router.get("/slots", response_model=SlotsOut)
async def get_slots(
    tenant: CurrentTenant,
    session: SessionDep,
    service_id: UUID,
    day: Annotated[date, Query(alias="date")],
    resource_id: UUID | None = None,
) -> SlotsOut:
    service, resource_ids = await _resolve(session, tenant.id, service_id, resource_id)
    ctx = await build_context(session, tenant, service, resource_ids, day, day)
    tz = ctx.tenant.timezone
    slots = slots_for_service(ctx, day, resource_ids)
    return SlotsOut(
        service_id=service.id,
        date=day,
        timezone=tenant.timezone,
        slots=[
            SlotOut(
                start=s.start.astimezone(tz),
                end=s.end.astimezone(tz),
                resource_ids=list(s.resource_ids),
                remaining=s.remaining,
            )
            for s in slots
        ],
    )


@router.get("/availability", response_model=AvailabilityOut)
async def get_availability(
    tenant: CurrentTenant,
    session: SessionDep,
    service_id: UUID,
    first_day: Annotated[date, Query(alias="from")],
    last_day: Annotated[date, Query(alias="to")],
    resource_id: UUID | None = None,
) -> AvailabilityOut:
    if last_day < first_day:
        raise HTTPException(422, "'to' deve ser >= 'from'")
    if last_day - first_day > timedelta(days=MAX_AVAILABILITY_DAYS - 1):
        raise HTTPException(
            422,
            f"Intervalo maximo de {MAX_AVAILABILITY_DAYS} dias",
        )
    service, resource_ids = await _resolve(session, tenant.id, service_id, resource_id)
    ctx = await build_context(session, tenant, service, resource_ids, first_day, last_day)
    return AvailabilityOut(
        service_id=service.id,
        timezone=tenant.timezone,
        days=available_days(ctx, first_day, last_day, resource_ids),
    )

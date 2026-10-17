from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.deps import CurrentAdmin, SessionDep
from app.models import Booking, Resource, Service, service_resources
from app.schemas.manage import (
    ResourceAdminOut,
    ResourceIn,
    ResourceUpdate,
    ServiceAdminOut,
    ServiceIn,
    ServiceUpdate,
)

router = APIRouter(prefix="/v1/admin", tags=["admin"])

ACTIVE = ("pendente", "confirmado")


async def _get_resource(session: AsyncSession, tenant_id: UUID, resource_id: UUID) -> Resource:
    resource = (
        await session.execute(
            select(Resource).where(
                Resource.id == resource_id,
                Resource.tenant_id == tenant_id,
                Resource.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if resource is None:
        raise AppError(404, "resource_not_found", "Profissional nao encontrado")
    return resource


async def _get_service(session: AsyncSession, tenant_id: UUID, service_id: UUID) -> Service:
    service = (
        await session.execute(
            select(Service).where(
                Service.id == service_id,
                Service.tenant_id == tenant_id,
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if service is None:
        raise AppError(404, "service_not_found", "Servico nao encontrado")
    return service


async def _count_future_bookings(session: AsyncSession, **filters) -> int:
    clauses = [getattr(Booking, k) == v for k, v in filters.items()]
    return (
        await session.scalar(
            select(func.count())
            .select_from(Booking)
            .where(*clauses, Booking.status.in_(ACTIVE), Booking.start_at > datetime.now(UTC))
        )
    ) or 0


# ---------- profissionais / agendas ----------


@router.get("/resources", response_model=list[ResourceAdminOut])
async def list_resources(admin: CurrentAdmin, session: SessionDep) -> list[Resource]:
    return list(
        (
            await session.execute(
                select(Resource)
                .where(Resource.tenant_id == admin.tenant_id, Resource.deleted_at.is_(None))
                .order_by(Resource.created_at, Resource.id)
            )
        ).scalars()
    )


@router.post("/resources", response_model=ResourceAdminOut, status_code=status.HTTP_201_CREATED)
async def create_resource(data: ResourceIn, admin: CurrentAdmin, session: SessionDep) -> Resource:
    resource = Resource(tenant_id=admin.tenant_id, name=data.name)
    session.add(resource)
    await session.commit()
    return resource


@router.patch("/resources/{resource_id}", response_model=ResourceAdminOut)
async def update_resource(
    resource_id: UUID, data: ResourceUpdate, admin: CurrentAdmin, session: SessionDep
) -> Resource:
    resource = await _get_resource(session, admin.tenant_id, resource_id)
    if data.name is not None:
        resource.name = data.name
    if data.is_active is not None:
        resource.is_active = data.is_active
    await session.commit()
    return resource


@router.delete("/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(resource_id: UUID, admin: CurrentAdmin, session: SessionDep) -> None:
    resource = await _get_resource(session, admin.tenant_id, resource_id)
    if await _count_future_bookings(session, resource_id=resource.id):
        raise AppError(409, "has_bookings", "Ha agendamentos futuros neste profissional")
    resource.deleted_at = datetime.now(UTC)
    resource.is_active = False
    await session.commit()


# ---------- servicos ----------


async def _service_out(session: AsyncSession, service: Service) -> ServiceAdminOut:
    linked = list(
        (
            await session.execute(
                select(service_resources.c.resource_id).where(
                    service_resources.c.service_id == service.id
                )
            )
        ).scalars()
    )
    return ServiceAdminOut(
        id=service.id,
        name=service.name,
        description=service.description,
        duration_minutes=service.duration_minutes,
        buffer_minutes=service.buffer_minutes,
        capacity=service.capacity,
        slot_interval_minutes=service.slot_interval_minutes,
        price_cents=service.price_cents,
        is_active=service.is_active,
        resource_ids=linked,
    )


async def _set_links(
    session: AsyncSession, tenant_id: UUID, service_id: UUID, resource_ids: list[UUID]
) -> None:
    for resource_id in set(resource_ids):
        await _get_resource(session, tenant_id, resource_id)
    await session.execute(
        delete(service_resources).where(service_resources.c.service_id == service_id)
    )
    for resource_id in set(resource_ids):
        await session.execute(
            insert(service_resources).values(service_id=service_id, resource_id=resource_id)
        )


@router.get("/services", response_model=list[ServiceAdminOut])
async def list_services(admin: CurrentAdmin, session: SessionDep) -> list[ServiceAdminOut]:
    services = (
        await session.execute(
            select(Service)
            .where(Service.tenant_id == admin.tenant_id, Service.deleted_at.is_(None))
            .order_by(Service.name, Service.id)
        )
    ).scalars()
    return [await _service_out(session, s) for s in services]


@router.post("/services", response_model=ServiceAdminOut, status_code=status.HTTP_201_CREATED)
async def create_service(
    data: ServiceIn, admin: CurrentAdmin, session: SessionDep
) -> ServiceAdminOut:
    service = Service(
        tenant_id=admin.tenant_id,
        **data.model_dump(exclude={"resource_ids"}),
    )
    session.add(service)
    await session.flush()
    if data.resource_ids:
        await _set_links(session, admin.tenant_id, service.id, data.resource_ids)
    await session.commit()
    return await _service_out(session, service)


@router.patch("/services/{service_id}", response_model=ServiceAdminOut)
async def update_service(
    service_id: UUID, data: ServiceUpdate, admin: CurrentAdmin, session: SessionDep
) -> ServiceAdminOut:
    service = await _get_service(session, admin.tenant_id, service_id)
    changes = data.model_dump(exclude_unset=True, exclude={"resource_ids"})
    for field, value in changes.items():
        if value is None and field in ("name", "duration_minutes", "buffer_minutes", "capacity"):
            raise AppError(422, "invalid_field", f"{field} nao pode ser vazio")
        setattr(service, field, value)
    if "resource_ids" in data.model_fields_set:
        await _set_links(session, admin.tenant_id, service.id, data.resource_ids or [])
    await session.commit()
    return await _service_out(session, service)


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: UUID, admin: CurrentAdmin, session: SessionDep) -> None:
    service = await _get_service(session, admin.tenant_id, service_id)
    if await _count_future_bookings(session, service_id=service.id):
        raise AppError(409, "has_bookings", "Ha agendamentos futuros neste servico")
    service.deleted_at = datetime.now(UTC)
    service.is_active = False
    await session.commit()

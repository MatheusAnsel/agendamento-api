from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import CurrentTenant, SessionDep
from app.models import Resource, Service, service_resources
from app.schemas.public import ResourceOut, ServiceOut, TenantConfigOut

router = APIRouter(prefix="/v1", tags=["publico"])


@router.get("/config", response_model=TenantConfigOut)
async def get_config(tenant: CurrentTenant) -> TenantConfigOut:
    return TenantConfigOut(
        name=tenant.name,
        slug=tenant.slug,
        timezone=tenant.timezone,
        availability_mode=tenant.availability_mode,
        min_notice_minutes=tenant.min_notice_minutes,
        max_advance_days=tenant.max_advance_days,
        form_config=tenant.form_config,
    )


async def _active_resources(session: SessionDep, tenant_id: UUID) -> list[Resource]:
    return list(
        (
            await session.execute(
                select(Resource)
                .where(
                    Resource.tenant_id == tenant_id,
                    Resource.is_active.is_(True),
                    Resource.deleted_at.is_(None),
                )
                .order_by(Resource.created_at, Resource.id)
            )
        ).scalars()
    )


@router.get("/resources", response_model=list[ResourceOut])
async def list_resources(tenant: CurrentTenant, session: SessionDep) -> list[ResourceOut]:
    return [ResourceOut(id=r.id, name=r.name) for r in await _active_resources(session, tenant.id)]


@router.get("/services", response_model=list[ServiceOut])
async def list_services(tenant: CurrentTenant, session: SessionDep) -> list[ServiceOut]:
    resources = await _active_resources(session, tenant.id)
    active_ids = [r.id for r in resources]
    services = (
        await session.execute(
            select(Service)
            .where(
                Service.tenant_id == tenant.id,
                Service.is_active.is_(True),
                Service.deleted_at.is_(None),
            )
            .order_by(Service.name, Service.id)
        )
    ).scalars()
    links: dict[UUID, set[UUID]] = {}
    for service_id, resource_id in (
        await session.execute(
            select(service_resources.c.service_id, service_resources.c.resource_id)
        )
    ).all():
        links.setdefault(service_id, set()).add(resource_id)

    out = []
    for s in services:
        linked = links.get(s.id)
        ids = [i for i in active_ids if i in linked] if linked else active_ids
        out.append(
            ServiceOut(
                id=s.id,
                name=s.name,
                description=s.description,
                duration_minutes=s.duration_minutes,
                capacity=s.capacity,
                price_cents=s.price_cents,
                resource_ids=ids,
            )
        )
    return out

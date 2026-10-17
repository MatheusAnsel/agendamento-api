from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentAdmin, SessionDep
from app.models import Tenant
from app.schemas.manage import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _out(tenant: Tenant) -> SettingsOut:
    return SettingsOut(
        name=tenant.name,
        slug=tenant.slug,
        timezone=tenant.timezone,
        availability_mode=tenant.availability_mode,  # type: ignore[arg-type]
        auto_confirm=tenant.auto_confirm,
        min_notice_minutes=tenant.min_notice_minutes,
        max_advance_days=tenant.max_advance_days,
        allowed_origins=tenant.allowed_origins or [],
        form_config=tenant.form_config,
    )


async def _tenant(session: AsyncSession, admin: CurrentAdmin) -> Tenant:
    tenant = await session.get(Tenant, admin.tenant_id)
    assert tenant is not None
    return tenant


@router.get("/settings", response_model=SettingsOut)
async def get_settings_(admin: CurrentAdmin, session: SessionDep) -> SettingsOut:
    return _out(await _tenant(session, admin))


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(
    data: SettingsUpdate, admin: CurrentAdmin, session: SessionDep
) -> SettingsOut:
    tenant = await _tenant(session, admin)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None:
            continue
        if field == "form_config":
            value = data.form_config.model_dump()  # type: ignore[union-attr]
        setattr(tenant, field, value)
    await session.commit()
    return _out(tenant)

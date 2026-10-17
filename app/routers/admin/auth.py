from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.ratelimit import rate_limit
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    generate_api_key,
    verify_password,
)
from app.deps import CurrentAdmin, SessionDep
from app.models import AdminUser, ApiKey, Tenant
from app.schemas.admin import (
    ApiKeyCreatedOut,
    ApiKeyCreateIn,
    ApiKeyOut,
    LoginIn,
    MeOut,
    TokenOut,
)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.post(
    "/login",
    response_model=TokenOut,
    dependencies=[Depends(rate_limit("login", "rate_limit_login_per_minute"))],
)
async def login(data: LoginIn, session: SessionDep) -> TokenOut:
    row = (
        await session.execute(
            select(AdminUser)
            .join(Tenant, Tenant.id == AdminUser.tenant_id)
            .where(
                Tenant.slug == data.tenant_slug.strip().lower(),
                Tenant.is_active.is_(True),
                Tenant.deleted_at.is_(None),
                AdminUser.email == data.email.strip().lower(),
                AdminUser.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()

    # Verifica sempre um hash, para nao revelar por tempo de resposta se o usuario existe.
    password_ok = verify_password(data.password, row.password_hash if row else DUMMY_PASSWORD_HASH)
    if row is None or not password_ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais invalidas")

    settings = get_settings()
    return TokenOut(
        access_token=create_access_token(row.id, row.tenant_id),
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.get("/me", response_model=MeOut)
async def me(admin: CurrentAdmin, session: SessionDep) -> MeOut:
    tenant = await session.get(Tenant, admin.tenant_id)
    assert tenant is not None
    return MeOut(
        id=admin.id,
        email=admin.email,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
    )


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(admin: CurrentAdmin, session: SessionDep) -> list[ApiKey]:
    return list(
        (
            await session.execute(
                select(ApiKey)
                .where(ApiKey.tenant_id == admin.tenant_id)
                .order_by(ApiKey.created_at.desc())
            )
        ).scalars()
    )


@router.post("/api-keys", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreateIn, admin: CurrentAdmin, session: SessionDep
) -> ApiKeyCreatedOut:
    plain, prefix, key_hash = generate_api_key()
    key = ApiKey(tenant_id=admin.tenant_id, label=data.label, key_prefix=prefix, key_hash=key_hash)
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return ApiKeyCreatedOut(
        id=key.id,
        label=key.label,
        key_prefix=key.key_prefix,
        is_active=key.is_active,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        key=plain,
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: UUID, admin: CurrentAdmin, session: SessionDep) -> None:
    key = (
        await session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == admin.tenant_id)
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chave nao encontrada")
    if key.revoked_at is None:
        key.is_active = False
        key.revoked_at = datetime.now(UTC)
        await session.commit()

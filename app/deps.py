"""Dependencias de autenticacao.

- get_tenant: identifica o negocio pela chave de API publica (header X-API-Key) e, quando a
  requisicao vem de um navegador (header Origin), exige que o site esteja na lista permitida.
- get_current_admin: identifica o dono pelo JWT (Authorization: Bearer ...).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.security import decode_access_token, hash_api_key
from app.db.session import get_session
from app.models import AdminUser, ApiKey, Tenant

LAST_USED_REFRESH = timedelta(hours=1)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def origin_allowed(origin: str, allowed: list[str]) -> bool:
    normalized = origin.strip().rstrip("/").lower()
    return normalized in {item.strip().rstrip("/").lower() for item in allowed}


async def get_tenant(
    request: Request,
    api_key: Annotated[str | None, Depends(_api_key_header)],
    session: SessionDep,
) -> Tenant:
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave de API ausente")

    row = (
        await session.execute(
            select(ApiKey, Tenant)
            .join(Tenant, Tenant.id == ApiKey.tenant_id)
            .where(
                ApiKey.key_hash == hash_api_key(api_key),
                ApiKey.is_active.is_(True),
                ApiKey.revoked_at.is_(None),
                Tenant.is_active.is_(True),
                Tenant.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave de API invalida")
    key, tenant = row

    origin = request.headers.get("origin")
    if origin and not origin_allowed(origin, tenant.allowed_origins or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origem nao permitida para esta chave")

    now = datetime.now(UTC)
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_REFRESH:
        await session.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=now))
        await session.commit()
    return tenant


async def get_current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
) -> AdminUser:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Token invalido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        claims = decode_access_token(credentials.credentials)
        admin_id, tenant_id = UUID(claims["sub"]), UUID(claims["tid"])
    except (jwt.PyJWTError, ValueError):
        raise unauthorized from None

    admin = (
        await session.execute(
            select(AdminUser).where(
                AdminUser.id == admin_id,
                AdminUser.tenant_id == tenant_id,
                AdminUser.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if admin is None:
        raise unauthorized
    return admin


CurrentTenant = Annotated[Tenant, Depends(get_tenant)]
CurrentAdmin = Annotated[AdminUser, Depends(get_current_admin)]

"""Comandos de administracao da plataforma (feitos por quem opera o sistema, nao pelo dono).

Exemplo:
    python -m app.cli create-tenant --name "Barbearia do Ze" --slug barbearia-ze \\
        --owner-email ze@exemplo.com --owner-password 'uma-senha-forte' \\
        --origin https://barbeariadoze.com.br
"""

import argparse
import re
import sys
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import generate_api_key, hash_password
from app.models import AdminUser, ApiKey, Resource, Tenant

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MIN_PASSWORD_LENGTH = 8


def create_tenant(
    session: Session,
    *,
    name: str,
    slug: str,
    owner_email: str,
    owner_password: str,
    timezone: str = "America/Sao_Paulo",
    origins: list[str] | None = None,
    resource_name: str = "Agenda principal",
) -> tuple[Tenant, str]:
    """Cria negocio, recurso padrao, dono e a primeira chave de API. Devolve (tenant, chave)."""
    slug = slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise ValueError("slug deve conter apenas letras minusculas, numeros e hifens")
    if len(owner_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A senha deve ter ao menos {MIN_PASSWORD_LENGTH} caracteres")
    ZoneInfo(timezone)  # levanta erro se o fuso nao existir
    if session.execute(select(Tenant.id).where(Tenant.slug == slug)).first():
        raise ValueError(f"Ja existe um negocio com o slug '{slug}'")

    tenant = Tenant(name=name, slug=slug, timezone=timezone, allowed_origins=origins or [])
    session.add(tenant)
    session.flush()
    session.add(Resource(tenant_id=tenant.id, name=resource_name))
    session.add(
        AdminUser(
            tenant_id=tenant.id,
            email=owner_email.strip().lower(),
            password_hash=hash_password(owner_password),
        )
    )
    plain, prefix, key_hash = generate_api_key()
    session.add(
        ApiKey(tenant_id=tenant.id, label="Site principal", key_prefix=prefix, key_hash=key_hash)
    )
    session.flush()
    return tenant, plain


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-tenant", help="Cria um negocio com o login do dono")
    p.add_argument("--name", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--owner-email", required=True)
    p.add_argument("--owner-password", required=True)
    p.add_argument("--timezone", default="America/Sao_Paulo")
    p.add_argument(
        "--origin",
        action="append",
        default=[],
        help="Site autorizado a usar a chave (repita para varios). Ex.: https://meusite.com.br",
    )
    args = parser.parse_args(argv)

    engine = create_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            tenant, key = create_tenant(
                session,
                name=args.name,
                slug=args.slug,
                owner_email=args.owner_email,
                owner_password=args.owner_password,
                timezone=args.timezone,
                origins=args.origin,
            )
            session.commit()
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(f"Negocio criado: {tenant.name} (slug: {tenant.slug})")
    print(f"Login do dono: {args.owner_email.strip().lower()}")
    print(f"Chave de API (guarde agora, ela nao sera mostrada de novo): {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

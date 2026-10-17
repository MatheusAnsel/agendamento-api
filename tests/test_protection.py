from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from helpers import headers
from sqlalchemy.orm import Session

from app.cli import expire_pending, main
from app.core.ratelimit import RateLimiter
from app.models import Booking, Customer, Service

pytestmark = pytest.mark.anyio


def test_limiter_sliding_window():
    limiter = RateLimiter()
    assert all(limiter.allow("k", 3, 60, now=t) for t in (0, 1, 2))
    assert not limiter.allow("k", 3, 60, now=3)
    assert limiter.allow("outro", 3, 60, now=3)
    assert limiter.allow("k", 3, 60, now=61)  # a primeira saiu da janela


async def test_login_is_rate_limited(client, env):
    body = {"tenant_slug": env["slug"], "email": "x@x.com", "password": "errada"}
    codes = [(await client.post("/v1/admin/login", json=body)).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]
    limited = await client.post("/v1/admin/login", json=body)
    assert limited.json()["code"] == "rate_limited"


async def test_booking_endpoint_is_rate_limited(client, env):
    codes = []
    for _ in range(12):
        response = await client.post("/v1/bookings", json={}, headers=headers(env))
        codes.append(response.status_code)
    assert codes[:10] == [422] * 10
    assert codes[10:] == [429, 429]


async def test_forwarded_for_uses_last_trusted_hop(client, env):
    body = {"tenant_slug": env["slug"], "email": "x@x.com", "password": "errada"}
    for _ in range(10):
        await client.post(
            "/v1/admin/login", json=body, headers={"X-Forwarded-For": "9.9.9.9, 1.1.1.1"}
        )
    blocked = await client.post(
        "/v1/admin/login", json=body, headers={"X-Forwarded-For": "8.8.8.8, 1.1.1.1"}
    )
    assert blocked.status_code == 429  # mesmo IP real (1.1.1.1), por mais que forjem o inicio
    other = await client.post(
        "/v1/admin/login", json=body, headers={"X-Forwarded-For": "8.8.8.8, 2.2.2.2"}
    )
    assert other.status_code == 401


def test_expire_pending(env, engine):
    now = datetime.now(UTC)
    with Session(engine) as s:
        customer = Customer(tenant_id=env["tenant_id"], name="X", phone="+5521900000000")
        s.add(customer)
        s.flush()
        service = s.get(Service, env["service_id"])

        def make(offset_hours, status):
            start = now + timedelta(hours=offset_hours)
            booking = Booking(
                tenant_id=env["tenant_id"],
                resource_id=env["resource_id"],
                service_id=service.id,
                customer_id=customer.id,
                start_at=start,
                end_at=start + timedelta(minutes=30),
                occupied_until=start + timedelta(minutes=30),
                status=status,
            )
            s.add(booking)
            return booking

        old_pending = make(-5, "pendente")
        future_pending = make(+5, "pendente")
        old_confirmed = make(-10, "confirmado")
        s.flush()
        assert expire_pending(s) == 1
        s.flush()
        s.refresh(old_pending), s.refresh(future_pending), s.refresh(old_confirmed)
        assert old_pending.status == "cancelado"
        assert old_pending.cancel_reason == "Expirado sem confirmacao"
        assert future_pending.status == "pendente"
        assert old_confirmed.status == "confirmado"
        s.rollback()


def test_cli_create_tenant_via_main(engine, capsys):
    slug = f"cli-{uuid4().hex[:6]}"
    code = main(
        [
            "create-tenant",
            "--name",
            "Via CLI",
            "--slug",
            slug,
            "--owner-email",
            "dono@exemplo.com",
            "--owner-password",
            "12345678",
            "--origin",
            "https://cli.com.br",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0 and "pk_" in out
    again = main(
        [
            "create-tenant",
            "--name",
            "Via CLI",
            "--slug",
            slug,
            "--owner-email",
            "dono@exemplo.com",
            "--owner-password",
            "12345678",
        ]
    )
    assert again == 1
    from sqlalchemy import delete

    from app.models import Tenant

    with Session(engine) as s:
        s.execute(delete(Tenant).where(Tenant.slug == slug))
        s.commit()

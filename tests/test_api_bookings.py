import asyncio
import uuid
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest
from helpers import future_day, headers
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, Service, Tenant

pytestmark = pytest.mark.anyio

TZ = ZoneInfo("America/Sao_Paulo")


def start_at(days=3, hour=9, minute=0) -> str:
    return datetime.combine(future_day(days), time(hour, minute), tzinfo=TZ).isoformat()


def payload(env, **overrides):
    body = {
        "service_id": str(env["service_id"]),
        "start_at": start_at(),
        "customer": {"name": "Maria Souza", "phone": "(21) 99999-1111"},
    }
    body.update(overrides)
    return body


async def book(client, env, key=None, **overrides):
    extra = {"Idempotency-Key": key} if key else {}
    return await client.post(
        "/v1/bookings", json=payload(env, **overrides), headers=headers(env, **extra)
    )


async def test_create_booking_and_consult(client, env):
    response = await book(client, env, consent_lgpd=True, notes="Primeira vez")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "confirmado"
    assert body["start"].endswith("-03:00") and "T09:00:00" in body["start"]
    assert body["service_name"] == "Esmaltacao"
    assert body["customer_name"] == "Maria Souza"

    fetched = await client.get(f"/v1/bookings/{body['token']}", headers=headers(env))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]
    assert (await client.get("/v1/bookings/inexistente", headers=headers(env))).status_code == 404


async def test_booked_slot_disappears_and_second_booking_conflicts(client, env):
    assert (await book(client, env)).status_code == 201
    slots = await client.get(
        "/v1/slots",
        params={"service_id": str(env["service_id"]), "date": future_day().isoformat()},
        headers=headers(env),
    )
    starts = [s["start"][11:16] for s in slots.json()["slots"]]
    assert "09:00" not in starts
    other = await book(client, env, customer={"name": "Ana", "phone": "21988887777"})
    assert other.status_code == 409
    assert other.json()["code"] == "slot_unavailable"


async def test_simultaneous_requests_only_one_wins(client, env):
    results = await asyncio.gather(
        *[
            book(client, env, customer={"name": f"Cliente {i}", "phone": f"2199000000{i}"})
            for i in range(6)
        ]
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409, 409]


async def test_idempotency_key_returns_same_booking(client, env):
    first = await book(client, env, key="abc-123")
    again = await book(client, env, key="abc-123")
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]


async def test_invalid_times_are_rejected(client, env):
    # fora do expediente, fora da grade e no passado
    for value in (start_at(hour=14), start_at(minute=15), start_at(days=-2)):
        response = await book(client, env, start_at=value)
        assert response.status_code == 409, value
    naive = await book(client, env, start_at="2030-01-01T09:00:00")
    assert naive.status_code == 422


async def test_form_validation_uses_tenant_config(client, env, engine):
    with Session(engine) as s:
        tenant = s.get(Tenant, env["tenant_id"])
        tenant.form_config = {
            "required_fields": ["name", "phone", "email", "consent_lgpd"],
            "optional_fields": ["notes"],
            "custom_fields": [
                {"key": "car_plate", "label": "Placa", "type": "text", "required": True}
            ],
        }
        s.commit()
    missing = await book(client, env)
    assert missing.status_code == 422
    ok = await book(
        client,
        env,
        customer={"name": "Joao", "phone": "+5521977776666", "email": "joao@email.com"},
        custom={"car_plate": "ABC1D23"},
        consent_lgpd=True,
    )
    assert ok.status_code == 201
    unknown = await book(
        client,
        env,
        start_at=start_at(hour=10),
        customer={"name": "Joao", "phone": "+5521977776666", "email": "joao@email.com"},
        custom={"car_plate": "ABC1D23", "outro": "x"},
        consent_lgpd=True,
    )
    assert unknown.status_code == 422
    with Session(engine) as s:
        booking = s.execute(
            select(Booking).where(Booking.tenant_id == env["tenant_id"])
        ).scalar_one()
        assert booking.custom_data == {"car_plate": "ABC1D23"}


@pytest.mark.parametrize("phone", ["123", "abc", "+55 21 99999-99999999999"])
async def test_invalid_phone(client, env, phone):
    response = await book(client, env, customer={"name": "X", "phone": phone})
    assert response.status_code == 422


async def test_phone_is_normalized_and_customer_reused(client, env, engine):
    await book(client, env, customer={"name": "Maria", "phone": "(21) 99999-1111"})
    await book(
        client,
        env,
        start_at=start_at(hour=10),
        customer={"name": "Maria S.", "phone": "+5521999991111"},
    )
    with Session(engine) as s:
        from app.models import Customer

        customers = (
            s.execute(select(Customer).where(Customer.tenant_id == env["tenant_id"]))
            .scalars()
            .all()
        )
        assert [c.phone for c in customers] == ["+5521999991111"]


async def test_limit_of_active_bookings_per_phone(client, env):
    for hour in (9, 10, 11):
        assert (await book(client, env, start_at=start_at(hour=hour))).status_code == 201
    over = await book(client, env, start_at=start_at(hour=11, minute=30))
    assert over.status_code == 409
    assert over.json()["code"] == "too_many_active_bookings"


async def test_honeypot_rejects_bots(client, env):
    response = await book(client, env, website="http://spam.com")
    assert response.status_code == 400


async def test_pending_when_auto_confirm_is_off(client, env, engine):
    with Session(engine) as s:
        s.get(Tenant, env["tenant_id"]).auto_confirm = False
        s.commit()
    response = await book(client, env)
    assert response.json()["status"] == "pendente"


async def test_cancel_frees_the_slot(client, env):
    created = (await book(client, env)).json()
    cancelled = await client.post(
        f"/v1/bookings/{created['token']}/cancel",
        json={"reason": "Imprevisto"},
        headers=headers(env),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelado"
    again = await client.post(f"/v1/bookings/{created['token']}/cancel", headers=headers(env))
    assert again.status_code == 409
    assert (
        await book(client, env, customer={"name": "Ana", "phone": "21988887777"})
    ).status_code == 201


async def test_price_and_duration_come_from_the_service(client, env, engine):
    with Session(engine) as s:
        service = s.get(Service, env["service_id"])
        service.price_cents = 4500
        service.duration_minutes = 40
        s.commit()
    body = (await book(client, env)).json()
    assert body["price_cents"] == 4500
    start = datetime.fromisoformat(body["start"]).astimezone(UTC)
    end = datetime.fromisoformat(body["end"]).astimezone(UTC)
    assert (end - start).total_seconds() == 40 * 60


async def test_other_tenant_cannot_read_booking(client, env, engine):
    from app.cli import create_tenant

    created = (await book(client, env)).json()
    with Session(engine) as s:
        tenant, other_key = create_tenant(
            s,
            name="Outro",
            slug=f"outro-{uuid.uuid4().hex[:6]}",
            owner_email="o@o.com",
            owner_password="12345678",
        )
        s.commit()
        other_id = tenant.id
    try:
        response = await client.get(
            f"/v1/bookings/{created['token']}", headers={"X-API-Key": other_key}
        )
        assert response.status_code == 404
    finally:
        with Session(engine) as s:
            s.delete(s.get(Tenant, other_id))
            s.commit()

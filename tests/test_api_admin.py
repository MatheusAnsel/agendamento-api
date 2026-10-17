import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from helpers import PASSWORD, SITE, future_day, headers
from sqlalchemy.orm import Session

from app.models import Tenant

pytestmark = pytest.mark.anyio

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
async def auth(client, env):
    login = await client.post(
        "/v1/admin/login",
        json={"tenant_slug": env["slug"], "email": "dona@exemplo.com", "password": PASSWORD},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def at(days=3, hour=9, minute=0) -> str:
    return datetime.combine(future_day(days), time(hour, minute), tzinfo=TZ).isoformat()


async def public_book(client, env, **overrides):
    body = {
        "service_id": str(env["service_id"]),
        "start_at": at(),
        "customer": {"name": "Maria", "phone": "21999991111"},
        **overrides,
    }
    return await client.post("/v1/bookings", json=body, headers=headers(env))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/admin/settings"),
        ("get", "/v1/admin/resources"),
        ("get", "/v1/admin/services"),
        ("get", "/v1/admin/blocks"),
        ("get", "/v1/admin/date-exceptions"),
        ("get", "/v1/admin/bookings"),
    ],
)
async def test_admin_routes_require_login(client, env, method, path):
    assert (await getattr(client, method)(path)).status_code == 401
    # a chave de API publica nao abre a area do dono
    assert (await getattr(client, method)(path, headers=headers(env))).status_code == 401


async def test_settings_roundtrip_and_validation(client, env, auth):
    current = (await client.get("/v1/admin/settings", headers=auth)).json()
    assert current["allowed_origins"] == [SITE]
    assert current["auto_confirm"] is True

    updated = await client.patch(
        "/v1/admin/settings",
        json={
            "auto_confirm": False,
            "min_notice_minutes": 120,
            "allowed_origins": ["https://novo.com.br/", "http://localhost:5173"],
            "form_config": {
                "required_fields": ["name", "phone"],
                "optional_fields": ["email"],
                "custom_fields": [{"key": "car_plate", "label": "Placa", "required": True}],
            },
        },
        headers=auth,
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["allowed_origins"] == ["https://novo.com.br", "http://localhost:5173"]
    assert body["auto_confirm"] is False
    cfg = (await client.get("/v1/config", headers=headers(env))).json()
    assert cfg["form_config"]["custom_fields"][0]["key"] == "car_plate"

    for bad in (
        {"timezone": "Marte/Olympus"},
        {"allowed_origins": ["site-sem-protocolo.com"]},
        {"max_advance_days": 0},
        {"form_config": {"custom_fields": [{"key": "Tem Espaco", "label": "x"}]}},
        {"form_config": {"custom_fields": [{"key": "tipo", "label": "x", "type": "select"}]}},
    ):
        assert (await client.patch("/v1/admin/settings", json=bad, headers=auth)).status_code == 422


async def test_resources_and_services_crud(client, env, auth):
    created = await client.post("/v1/admin/resources", json={"name": "Carla"}, headers=auth)
    assert created.status_code == 201
    carla = created.json()["id"]

    service = await client.post(
        "/v1/admin/services",
        json={
            "name": "Corte",
            "duration_minutes": 40,
            "buffer_minutes": 10,
            "slot_interval_minutes": 0,
            "price_cents": 5000,
            "resource_ids": [carla],
        },
        headers=auth,
    )
    assert service.status_code == 201
    assert service.json()["resource_ids"] == [carla]
    service_id = service.json()["id"]

    for bad in ({"duration_minutes": 25}, {"buffer_minutes": 5}, {"slot_interval_minutes": 15}):
        response = await client.post(
            "/v1/admin/services", json={"name": "X", "duration_minutes": 30, **bad}, headers=auth
        )
        assert response.status_code == 422, bad

    patched = await client.patch(
        f"/v1/admin/services/{service_id}",
        json={"price_cents": 6000, "slot_interval_minutes": None},
        headers=auth,
    )
    assert patched.json()["price_cents"] == 6000
    assert patched.json()["slot_interval_minutes"] is None
    assert (
        await client.patch(f"/v1/admin/services/{service_id}", json={"name": None}, headers=auth)
    ).status_code == 422

    public = (await client.get("/v1/services", headers=headers(env))).json()
    corte = next(s for s in public if s["id"] == service_id)
    assert corte["resource_ids"] == [carla]

    other = await client.post(
        "/v1/admin/services",
        json={"name": "Y", "duration_minutes": 30, "resource_ids": [str(uuid.uuid4())]},
        headers=auth,
    )
    assert other.status_code == 404

    assert (
        await client.delete(f"/v1/admin/services/{service_id}", headers=auth)
    ).status_code == 204
    ids = [s["id"] for s in (await client.get("/v1/admin/services", headers=auth)).json()]
    assert service_id not in ids
    assert (await client.delete(f"/v1/admin/resources/{carla}", headers=auth)).status_code == 204


async def test_cannot_delete_resource_with_future_bookings(client, env, auth):
    assert (await public_book(client, env)).status_code == 201
    response = await client.delete(f"/v1/admin/resources/{env['resource_id']}", headers=auth)
    assert response.status_code == 409
    response = await client.delete(f"/v1/admin/services/{env['service_id']}", headers=auth)
    assert response.status_code == 409


async def test_weekly_rules_replace_changes_slots(client, env, auth):
    day = future_day(3)
    url = f"/v1/admin/resources/{env['resource_id']}/weekly-rules"
    rules = [{"weekday": day.weekday(), "start_time": "13:00:00", "end_time": "14:00:00"}]
    replaced = await client.put(url, json={"rules": rules}, headers=auth)
    assert replaced.status_code == 200 and len(replaced.json()) == 1
    assert len((await client.get(url, headers=auth)).json()) == 1

    slots = await client.get(
        "/v1/slots",
        params={"service_id": str(env["service_id"]), "date": day.isoformat()},
        headers=headers(env),
    )
    assert [s["start"][11:16] for s in slots.json()["slots"]] == ["13:00", "13:30"]

    invalid = await client.put(
        url,
        json={"rules": [{"weekday": 9, "start_time": "09:00:00", "end_time": "10:00:00"}]},
        headers=auth,
    )
    assert invalid.status_code == 422
    inverted = await client.put(
        url,
        json={"rules": [{"weekday": 1, "start_time": "10:00:00", "end_time": "09:00:00"}]},
        headers=auth,
    )
    assert inverted.status_code == 422


async def test_exceptions_and_blocks_change_availability(client, env, auth):
    day = future_day(3)
    params = {"service_id": str(env["service_id"]), "date": day.isoformat()}

    closed = await client.post(
        "/v1/admin/date-exceptions",
        json={"date": day.isoformat(), "kind": "closed", "reason": "Feriado"},
        headers=auth,
    )
    assert closed.status_code == 201
    assert (await client.get("/v1/slots", params=params, headers=headers(env))).json()[
        "slots"
    ] == []
    assert (
        await client.delete(f"/v1/admin/date-exceptions/{closed.json()['id']}", headers=auth)
    ).status_code == 204

    custom = await client.post(
        "/v1/admin/date-exceptions",
        json={
            "date": day.isoformat(),
            "kind": "custom_hours",
            "start_time": "10:00:00",
            "end_time": "11:00:00",
        },
        headers=auth,
    )
    assert custom.status_code == 201
    slots = (await client.get("/v1/slots", params=params, headers=headers(env))).json()["slots"]
    assert [s["start"][11:16] for s in slots] == ["10:00", "10:30"]
    bad = await client.post(
        "/v1/admin/date-exceptions",
        json={"date": day.isoformat(), "kind": "custom_hours"},
        headers=auth,
    )
    assert bad.status_code == 422

    block = await client.post(
        "/v1/admin/blocks",
        json={"start_at": at(hour=10), "end_at": at(hour=10, minute=30), "reason": "Medico"},
        headers=auth,
    )
    assert block.status_code == 201
    slots = (await client.get("/v1/slots", params=params, headers=headers(env))).json()["slots"]
    assert [s["start"][11:16] for s in slots] == ["10:30"]
    assert len((await client.get("/v1/admin/blocks", headers=auth)).json()) == 1
    assert (
        await client.delete(f"/v1/admin/blocks/{block.json()['id']}", headers=auth)
    ).status_code == 204
    inverted = await client.post(
        "/v1/admin/blocks", json={"start_at": at(hour=11), "end_at": at(hour=10)}, headers=auth
    )
    assert inverted.status_code == 422


async def test_booking_lifecycle_from_the_owner_side(client, env, auth, engine):
    with Session(engine) as s:
        s.get(Tenant, env["tenant_id"]).auto_confirm = False
        s.commit()
    created = (await public_book(client, env)).json()
    assert created["status"] == "pendente"

    listed = (await client.get("/v1/admin/bookings", headers=auth)).json()
    assert len(listed) == 1
    row = listed[0]
    assert row["customer_phone"] == "+5521999991111"
    booking_id = row["id"]

    assert (
        await client.post(f"/v1/admin/bookings/{booking_id}/complete", headers=auth)
    ).status_code == 409
    confirmed = await client.post(f"/v1/admin/bookings/{booking_id}/confirm", headers=auth)
    assert confirmed.json()["status"] == "confirmado"
    assert (
        await client.post(f"/v1/admin/bookings/{booking_id}/confirm", headers=auth)
    ).status_code == 409

    moved = await client.post(
        f"/v1/admin/bookings/{booking_id}/reschedule", json={"start_at": at(hour=11)}, headers=auth
    )
    assert moved.status_code == 200
    assert "T11:00:00" in moved.json()["start"]
    # o horario antigo voltou a ficar livre
    assert (
        await public_book(client, env, customer={"name": "Ana", "phone": "21988887777"})
    ).status_code == 201
    # e o novo esta ocupado
    clash = await client.post(
        f"/v1/admin/bookings/{booking_id}/reschedule", json={"start_at": at(hour=9)}, headers=auth
    )
    assert clash.status_code == 409
    outside = await client.post(
        f"/v1/admin/bookings/{booking_id}/reschedule", json={"start_at": at(hour=15)}, headers=auth
    )
    assert outside.status_code == 409

    done = await client.post(f"/v1/admin/bookings/{booking_id}/complete", headers=auth)
    assert done.json()["status"] == "concluido"
    assert (
        await client.post(f"/v1/admin/bookings/{booking_id}/cancel", headers=auth)
    ).status_code == 409

    filtered = (
        await client.get("/v1/admin/bookings", params={"status": "concluido"}, headers=auth)
    ).json()
    assert [b["id"] for b in filtered] == [booking_id]
    by_day = (
        await client.get(
            "/v1/admin/bookings",
            params={"date_from": future_day().isoformat(), "date_to": future_day().isoformat()},
            headers=auth,
        )
    ).json()
    assert len(by_day) == 2
    assert (
        await client.get("/v1/admin/bookings", params={"status": "xyz"}, headers=auth)
    ).status_code == 422


async def test_owner_cancel_and_no_show(client, env, auth):
    first = (await public_book(client, env)).json()
    second = (await public_book(client, env, start_at=at(hour=10))).json()
    listed = {b["id"]: b for b in (await client.get("/v1/admin/bookings", headers=auth)).json()}
    assert len(listed) == 2
    ids = {first["id"], second["id"]}
    assert set(listed) == ids
    cancelled = await client.post(
        f"/v1/admin/bookings/{first['id']}/cancel",
        json={"reason": "Dono precisou fechar"},
        headers=auth,
    )
    assert cancelled.json()["status"] == "cancelado"
    assert cancelled.json()["cancel_reason"] == "Dono precisou fechar"
    no_show = await client.post(f"/v1/admin/bookings/{second['id']}/no-show", headers=auth)
    assert no_show.json()["status"] == "nao_compareceu"

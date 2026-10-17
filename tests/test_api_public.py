import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.cli import create_tenant
from app.core.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models import Resource, Service, Tenant, WeeklyRule

pytestmark = pytest.mark.anyio

SITE = "https://site.com.br"
PASSWORD = "senha-do-dono-123"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def env(engine):
    """Negocio completo gravado de verdade (commit), removido ao final do teste."""
    slug = f"teste-{uuid.uuid4().hex[:8]}"
    with Session(engine) as s:
        tenant, key = create_tenant(
            s,
            name="Esmalteria Teste",
            slug=slug,
            owner_email="Dona@Exemplo.com",
            owner_password=PASSWORD,
            origins=[SITE],
        )
        resource = s.execute(select(Resource).where(Resource.tenant_id == tenant.id)).scalar_one()
        service = Service(tenant_id=tenant.id, name="Esmaltacao", duration_minutes=30)
        s.add(service)
        s.flush()
        for weekday in range(7):
            s.add(
                WeeklyRule(
                    tenant_id=tenant.id,
                    resource_id=resource.id,
                    weekday=weekday,
                    start_time=time(9, 0),
                    end_time=time(12, 0),
                )
            )
        s.commit()
        data = {
            "tenant_id": tenant.id,
            "slug": slug,
            "key": key,
            "resource_id": resource.id,
            "service_id": service.id,
        }
    yield data
    with Session(engine) as s:
        s.execute(delete(Tenant).where(Tenant.id == data["tenant_id"]))
        s.commit()


@pytest.fixture
async def client():
    eng = create_async_engine(get_settings().database_url, poolclass=NullPool)
    maker = async_sessionmaker(eng, expire_on_commit=False)

    async def override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await eng.dispose()


def headers(env, **extra):
    return {"X-API-Key": env["key"], **extra}


def future_day(days=3) -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date() + timedelta(days=days)


async def test_requires_valid_api_key(client, env):
    assert (await client.get("/v1/config")).status_code == 401
    assert (await client.get("/v1/config", headers={"X-API-Key": "pk_invalida"})).status_code == 401
    response = await client.get("/v1/config", headers=headers(env))
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Esmalteria Teste"
    assert body["form_config"]["required_fields"] == ["name", "phone"]


async def test_origin_allowlist(client, env):
    ok = await client.get("/v1/config", headers=headers(env, Origin=SITE + "/"))
    assert ok.status_code == 200
    ok_case = await client.get("/v1/config", headers=headers(env, Origin=SITE.upper()))
    assert ok_case.status_code == 200
    blocked = await client.get("/v1/config", headers=headers(env, Origin="https://malicioso.com"))
    assert blocked.status_code == 403


async def test_revoked_key_stops_working(client, env):
    login = await client.post(
        "/v1/admin/login",
        json={"tenant_slug": env["slug"], "email": "dona@exemplo.com", "password": PASSWORD},
    )
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    keys = (await client.get("/v1/admin/api-keys", headers=auth)).json()
    assert len(keys) == 1
    assert (
        await client.delete(f"/v1/admin/api-keys/{keys[0]['id']}", headers=auth)
    ).status_code == 204
    assert (await client.get("/v1/config", headers=headers(env))).status_code == 401


async def test_resources_and_services(client, env):
    resources = (await client.get("/v1/resources", headers=headers(env))).json()
    assert [r["id"] for r in resources] == [str(env["resource_id"])]
    services = (await client.get("/v1/services", headers=headers(env))).json()
    assert len(services) == 1
    assert services[0]["name"] == "Esmaltacao"
    assert services[0]["duration_minutes"] == 30
    assert services[0]["resource_ids"] == [str(env["resource_id"])]


async def test_slots_for_day(client, env):
    day = future_day()
    response = await client.get(
        "/v1/slots",
        params={"service_id": str(env["service_id"]), "date": day.isoformat()},
        headers=headers(env),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "America/Sao_Paulo"
    starts = [s["start"][11:16] for s in body["slots"]]
    assert starts == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"]
    assert body["slots"][0]["start"].endswith("-03:00")
    assert body["slots"][0]["resource_ids"] == [str(env["resource_id"])]


async def test_slots_unknown_service_and_resource(client, env):
    day = future_day().isoformat()
    unknown = await client.get(
        "/v1/slots",
        params={"service_id": str(uuid.uuid4()), "date": day},
        headers=headers(env),
    )
    assert unknown.status_code == 404
    bad_resource = await client.get(
        "/v1/slots",
        params={
            "service_id": str(env["service_id"]),
            "date": day,
            "resource_id": str(uuid.uuid4()),
        },
        headers=headers(env),
    )
    assert bad_resource.status_code == 404


async def test_availability_range(client, env):
    first, last = future_day(1), future_day(5)
    response = await client.get(
        "/v1/availability",
        params={
            "service_id": str(env["service_id"]),
            "from": first.isoformat(),
            "to": last.isoformat(),
        },
        headers=headers(env),
    )
    assert response.status_code == 200
    assert response.json()["days"] == [(first + timedelta(days=i)).isoformat() for i in range(5)]


async def test_availability_range_validation(client, env):
    params = {"service_id": str(env["service_id"])}
    too_long = await client.get(
        "/v1/availability",
        params={**params, "from": future_day(1).isoformat(), "to": future_day(100).isoformat()},
        headers=headers(env),
    )
    assert too_long.status_code == 422
    inverted = await client.get(
        "/v1/availability",
        params={**params, "from": future_day(5).isoformat(), "to": future_day(1).isoformat()},
        headers=headers(env),
    )
    assert inverted.status_code == 422


async def test_admin_login_and_me(client, env):
    bad = await client.post(
        "/v1/admin/login",
        json={"tenant_slug": env["slug"], "email": "dona@exemplo.com", "password": "errada"},
    )
    assert bad.status_code == 401
    unknown = await client.post(
        "/v1/admin/login",
        json={"tenant_slug": "nao-existe", "email": "dona@exemplo.com", "password": PASSWORD},
    )
    assert unknown.status_code == 401

    assert (await client.get("/v1/admin/me")).status_code == 401
    assert (
        await client.get("/v1/admin/me", headers={"Authorization": "Bearer lixo"})
    ).status_code == 401

    login = await client.post(
        "/v1/admin/login",
        json={
            "tenant_slug": env["slug"].upper(),
            "email": " DONA@exemplo.com ",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200
    me = await client.get(
        "/v1/admin/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "dona@exemplo.com"
    assert me.json()["tenant_slug"] == env["slug"]


async def test_create_api_key_returns_key_once_and_it_works(client, env):
    login = await client.post(
        "/v1/admin/login",
        json={"tenant_slug": env["slug"], "email": "dona@exemplo.com", "password": PASSWORD},
    )
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post("/v1/admin/api-keys", json={"label": "Landing"}, headers=auth)
    assert created.status_code == 201
    new_key = created.json()["key"]
    assert (await client.get("/v1/config", headers={"X-API-Key": new_key})).status_code == 200
    listed = (await client.get("/v1/admin/api-keys", headers=auth)).json()
    assert len(listed) == 2
    assert all("key" not in k and "key_hash" not in k for k in listed)


def test_cli_validations(engine):
    with Session(engine) as s:
        with pytest.raises(ValueError):
            create_tenant(
                s, name="x", slug="Slug Invalido", owner_email="a@b.com", owner_password="12345678"
            )
        with pytest.raises(ValueError):
            create_tenant(
                s, name="x", slug="ok-slug", owner_email="a@b.com", owner_password="curta"
            )
        s.rollback()

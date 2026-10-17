import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta

import pytest
from alembic.config import Config
from helpers import PASSWORD, SITE
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from alembic import command
from app.cli import create_tenant
from app.core.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models import Booking, Customer, Resource, Service, Tenant, WeeklyRule


@pytest.fixture(scope="session")
def engine():
    """Aplica as migrations no banco configurado (DATABASE_URL) e devolve o engine.

    Os testes rodam dentro de uma transacao que sofre rollback, entao nao deixam dados.
    """
    command.upgrade(Config("alembic.ini"), "head")
    eng = create_engine(get_settings().database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def base_data(session: Session) -> dict:
    """Um tenant com dois recursos, um servico individual e um cliente."""
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="Barbearia Teste", slug=f"barbearia-{suffix}")
    session.add(tenant)
    session.flush()

    resource_a = Resource(tenant_id=tenant.id, name="Profissional A")
    resource_b = Resource(tenant_id=tenant.id, name="Profissional B")
    service = Service(tenant_id=tenant.id, name="Corte", duration_minutes=30, buffer_minutes=10)
    customer = Customer(tenant_id=tenant.id, name="Joao", phone="+5521999999999")
    session.add_all([resource_a, resource_b, service, customer])
    session.flush()

    return {
        "tenant": tenant,
        "resource_a": resource_a,
        "resource_b": resource_b,
        "service": service,
        "customer": customer,
        "t0": datetime(2026, 11, 3, 13, 0, tzinfo=UTC),  # 10:00 em Sao Paulo
    }


def make_booking_kwargs(data: dict, resource, start, minutes=30, buffer=10, **extra) -> dict:
    end = start + timedelta(minutes=minutes)
    return {
        "tenant_id": data["tenant"].id,
        "resource_id": resource.id,
        "service_id": data["service"].id,
        "customer_id": data["customer"].id,
        "start_at": start,
        "end_at": end,
        "occupied_until": end + timedelta(minutes=buffer),
        **extra,
    }


# ---- fixtures da API (dados gravados de verdade, removidos ao final) ----


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
        s.execute(delete(Booking).where(Booking.tenant_id == data["tenant_id"]))
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

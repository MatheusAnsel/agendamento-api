import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.models import Customer, Resource, Service, Tenant


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

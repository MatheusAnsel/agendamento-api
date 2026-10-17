from datetime import time, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import TIME_STEP_MINUTES
from app.models import Booking, DateException, Service, Tenant, WeeklyRule
from tests.conftest import make_booking_kwargs


def add_booking(session: Session, data: dict, resource, start, **kwargs) -> Booking:
    booking = Booking(**make_booking_kwargs(data, resource, start, **kwargs))
    session.add(booking)
    session.flush()
    return booking


def assert_rejected(session: Session, data: dict, resource, start, **kwargs) -> None:
    with pytest.raises(IntegrityError) as exc:
        with session.begin_nested():
            add_booking(session, data, resource, start, **kwargs)
    # 23P01 = exclusion_violation
    assert exc.value.orig.sqlstate == "23P01"


def test_overlapping_booking_same_resource_is_rejected(session, base_data):
    d = base_data
    add_booking(session, d, d["resource_a"], d["t0"])
    assert_rejected(session, d, d["resource_a"], d["t0"] + timedelta(minutes=15))


def test_identical_start_is_rejected(session, base_data):
    d = base_data
    add_booking(session, d, d["resource_a"], d["t0"])
    assert_rejected(session, d, d["resource_a"], d["t0"])


def test_buffer_blocks_the_next_start(session, base_data):
    d = base_data
    # Atendimento 10:00-10:30 com buffer de 10 min ocupa o recurso ate 10:40.
    add_booking(session, d, d["resource_a"], d["t0"])
    assert_rejected(session, d, d["resource_a"], d["t0"] + timedelta(minutes=30))
    add_booking(session, d, d["resource_a"], d["t0"] + timedelta(minutes=40))


def test_other_resource_can_book_same_time(session, base_data):
    d = base_data
    add_booking(session, d, d["resource_a"], d["t0"])
    add_booking(session, d, d["resource_b"], d["t0"])


def test_cancelled_booking_frees_the_slot(session, base_data):
    d = base_data
    first = add_booking(session, d, d["resource_a"], d["t0"])
    first.status = "cancelado"
    session.flush()
    add_booking(session, d, d["resource_a"], d["t0"])


def test_non_exclusive_service_allows_group_bookings(session, base_data):
    d = base_data
    add_booking(session, d, d["resource_a"], d["t0"], is_exclusive=False)
    add_booking(session, d, d["resource_a"], d["t0"], is_exclusive=False)


def test_invalid_status_is_rejected(session, base_data):
    d = base_data
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            add_booking(session, d, d["resource_a"], d["t0"], status="inexistente")


def test_booking_token_is_unique_and_generated(session, base_data):
    d = base_data
    a = add_booking(session, d, d["resource_a"], d["t0"])
    b = add_booking(session, d, d["resource_b"], d["t0"])
    assert a.token and b.token and a.token != b.token
    assert len(a.token) >= 32


def test_idempotency_key_is_unique_per_tenant(session, base_data):
    d = base_data
    add_booking(session, d, d["resource_a"], d["t0"], idempotency_key="abc")
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            add_booking(
                session,
                d,
                d["resource_b"],
                d["t0"] + timedelta(hours=3),
                idempotency_key="abc",
            )


def test_tenant_defaults(session):
    tenant = Tenant(name="Oficina", slug="oficina-defaults")
    session.add(tenant)
    session.flush()
    session.refresh(tenant)
    assert tenant.timezone == "America/Sao_Paulo"
    assert tenant.auto_confirm is True
    assert tenant.availability_mode == "rules"
    assert tenant.form_config["required_fields"] == ["name", "phone"]
    assert tenant.allowed_origins == []


def test_invalid_weekday_is_rejected(session, base_data):
    d = base_data
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                WeeklyRule(
                    tenant_id=d["tenant"].id,
                    resource_id=d["resource_a"].id,
                    weekday=7,
                    start_time=time(9),
                    end_time=time(12),
                )
            )
            session.flush()


def test_weekly_rule_end_must_be_after_start(session, base_data):
    d = base_data
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                WeeklyRule(
                    tenant_id=d["tenant"].id,
                    resource_id=d["resource_a"].id,
                    weekday=0,
                    start_time=time(12),
                    end_time=time(9),
                )
            )
            session.flush()


def test_closed_exception_cannot_have_times(session, base_data):
    d = base_data
    from datetime import date

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                DateException(
                    tenant_id=d["tenant"].id,
                    date=date(2026, 12, 25),
                    kind="closed",
                    start_time=time(9),
                    end_time=time(12),
                )
            )
            session.flush()
    # Valido: fechado sem horarios, e horario especial com intervalo.
    session.add(DateException(tenant_id=d["tenant"].id, date=date(2026, 12, 25), kind="closed"))
    session.add(
        DateException(
            tenant_id=d["tenant"].id,
            date=date(2026, 12, 24),
            kind="custom_hours",
            start_time=time(9),
            end_time=time(12),
        )
    )
    session.flush()


def make_service(data: dict, **overrides) -> Service:
    values = {
        "tenant_id": data["tenant"].id,
        "name": "Servico de teste",
        "duration_minutes": 40,
        "buffer_minutes": 10,
    }
    values.update(overrides)
    return Service(**values)


def test_time_step_is_ten_minutes():
    assert TIME_STEP_MINUTES == 10


def test_service_accepts_multiples_of_ten(session, base_data):
    session.add(make_service(base_data, duration_minutes=70, buffer_minutes=0))
    session.add(make_service(base_data, slot_interval_minutes=20))
    session.add(make_service(base_data, slot_interval_minutes=None))
    # 0 e aceito e significa "igual a duracao" (um atendimento logo apos o outro).
    session.add(make_service(base_data, slot_interval_minutes=0))
    session.flush()


def test_service_rejects_negative_slot_interval(session, base_data):
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(make_service(base_data, slot_interval_minutes=-10))
            session.flush()


@pytest.mark.parametrize(
    "field, value",
    [
        ("duration_minutes", 25),
        ("duration_minutes", 45),
        ("buffer_minutes", 5),
        ("buffer_minutes", 15),
        ("slot_interval_minutes", 15),
        ("slot_interval_minutes", 25),
    ],
)
def test_service_rejects_values_that_are_not_multiples_of_ten(session, base_data, field, value):
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(make_service(base_data, **{field: value}))
            session.flush()

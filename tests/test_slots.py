from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.services.slots import (
    BlockSpec,
    BookingSpec,
    DateExceptionSpec,
    ServiceSpec,
    SlotContext,
    TenantRules,
    WeeklyWindow,
    available_days,
    slots_for_day,
    slots_for_service,
)

SP = ZoneInfo("America/Sao_Paulo")
NY = ZoneInfo("America/New_York")

DAY = date(2026, 11, 3)  # terca-feira (weekday 1)
TUESDAY = 1
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

RES_A = uuid4()
RES_B = uuid4()
SERVICE_ID = uuid4()


def local(day: date, hour: int, minute: int = 0, tz: ZoneInfo = SP) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(UTC)


def hhmm(slots, tz: ZoneInfo = SP) -> list[str]:
    return [s.start.astimezone(tz).strftime("%H:%M") for s in slots]


def make_ctx(
    *,
    weekly=None,
    duration=30,
    buffer=0,
    capacity=1,
    interval=None,
    tz=SP,
    mode="rules",
    min_notice=0,
    max_advance=60,
    now=NOW,
    **extra,
) -> SlotContext:
    if weekly is None:
        weekly = [
            WeeklyWindow(RES_A, TUESDAY, time(9), time(12)),
        ]
    return SlotContext(
        tenant=TenantRules(
            timezone=tz,
            availability_mode=mode,
            min_notice_minutes=min_notice,
            max_advance_days=max_advance,
        ),
        service=ServiceSpec(
            id=SERVICE_ID,
            duration_minutes=duration,
            buffer_minutes=buffer,
            capacity=capacity,
            slot_interval_minutes=interval,
        ),
        now=now,
        weekly=weekly,
        **extra,
    )


def booking(start: datetime, minutes=30, buffer=0, resource=RES_A, **kwargs) -> BookingSpec:
    end = start + timedelta(minutes=minutes)
    return BookingSpec(
        resource_id=resource,
        service_id=kwargs.pop("service_id", SERVICE_ID),
        start_at=start,
        occupied_until=end + timedelta(minutes=buffer),
        **kwargs,
    )


# --- Regra semanal e granularidade -------------------------------------------------------


def test_weekly_rule_with_two_intervals():
    ctx = make_ctx(
        weekly=[
            WeeklyWindow(RES_A, TUESDAY, time(9), time(12)),
            WeeklyWindow(RES_A, TUESDAY, time(14), time(18)),
        ]
    )
    slots = hhmm(slots_for_day(ctx, DAY, RES_A))
    assert len(slots) == 6 + 8
    assert slots[0] == "09:00"
    assert "11:30" in slots and "12:00" not in slots and "13:30" not in slots
    assert slots[-1] == "17:30"


def test_other_weekday_has_no_slots():
    ctx = make_ctx()
    assert slots_for_day(ctx, DAY + timedelta(days=1), RES_A) == []


def test_slot_interval_smaller_than_duration():
    ctx = make_ctx(duration=30, interval=10)
    slots = hhmm(slots_for_day(ctx, DAY, RES_A))
    assert len(slots) == 16
    assert slots[:3] == ["09:00", "09:10", "09:20"]
    assert slots[-1] == "11:30"


def test_window_shorter_than_service_gives_nothing():
    ctx = make_ctx(weekly=[WeeklyWindow(RES_A, TUESDAY, time(9), time(9, 20))], duration=30)
    assert slots_for_day(ctx, DAY, RES_A) == []


def test_overlapping_weekly_windows_are_merged_without_duplicates():
    ctx = make_ctx(
        weekly=[
            WeeklyWindow(RES_A, TUESDAY, time(9), time(12)),
            WeeklyWindow(RES_A, TUESDAY, time(11), time(13)),
        ]
    )
    slots = hhmm(slots_for_day(ctx, DAY, RES_A))
    assert len(slots) == 8
    assert slots.count("11:00") == 1 and slots[-1] == "12:30"


def test_slots_are_returned_in_utc():
    slot = slots_for_day(make_ctx(), DAY, RES_A)[0]
    assert slot.start.utcoffset() == timedelta(0)
    assert slot.start == datetime(2026, 11, 3, 12, 0, tzinfo=UTC)  # 09:00 em Sao Paulo (UTC-3)
    assert slot.end - slot.start == timedelta(minutes=30)
    assert slot.remaining == 1


def test_naive_now_is_rejected():
    ctx = make_ctx(now=datetime(2026, 11, 1, 12, 0))
    with pytest.raises(ValueError):
        slots_for_day(ctx, DAY, RES_A)


# --- Excecoes por data e modo open_dates -----------------------------------------------


def test_closed_exception_closes_the_day():
    ctx = make_ctx(exceptions=[DateExceptionSpec(None, DAY, "closed")])
    assert slots_for_day(ctx, DAY, RES_A) == []


def test_closed_exception_for_one_resource_keeps_the_other_open():
    weekly = [
        WeeklyWindow(RES_A, TUESDAY, time(9), time(12)),
        WeeklyWindow(RES_B, TUESDAY, time(9), time(12)),
    ]
    ctx = make_ctx(weekly=weekly, exceptions=[DateExceptionSpec(RES_A, DAY, "closed")])
    assert slots_for_day(ctx, DAY, RES_A) == []
    assert len(slots_for_day(ctx, DAY, RES_B)) == 6


def test_custom_hours_replace_the_weekly_rule():
    ctx = make_ctx(exceptions=[DateExceptionSpec(None, DAY, "custom_hours", time(10), time(11))])
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["10:00", "10:30"]


def test_custom_hours_accept_several_intervals_in_the_same_day():
    ctx = make_ctx(
        exceptions=[
            DateExceptionSpec(None, DAY, "custom_hours", time(8), time(9)),
            DateExceptionSpec(None, DAY, "custom_hours", time(15), time(16)),
        ]
    )
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["08:00", "08:30", "15:00", "15:30"]


def test_resource_custom_hours_win_over_tenant_wide_custom_hours():
    weekly = [
        WeeklyWindow(RES_A, TUESDAY, time(9), time(12)),
        WeeklyWindow(RES_B, TUESDAY, time(9), time(12)),
    ]
    ctx = make_ctx(
        weekly=weekly,
        exceptions=[
            DateExceptionSpec(None, DAY, "custom_hours", time(10), time(11)),
            DateExceptionSpec(RES_A, DAY, "custom_hours", time(13), time(14)),
        ],
    )
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["13:00", "13:30"]
    assert hhmm(slots_for_day(ctx, DAY, RES_B)) == ["10:00", "10:30"]


def test_exception_on_another_date_has_no_effect():
    other = DateExceptionSpec(None, DAY + timedelta(days=7), "closed")
    assert len(slots_for_day(make_ctx(exceptions=[other]), DAY, RES_A)) == 6


def test_open_dates_mode_only_offers_published_days():
    published = DateExceptionSpec(None, DAY, "custom_hours", time(14), time(15))
    ctx = make_ctx(mode="open_dates", exceptions=[published])
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["14:00", "14:30"]
    # A regra semanal e ignorada: um dia sem publicacao fica fechado.
    assert slots_for_day(make_ctx(mode="open_dates"), DAY, RES_A) == []


# --- Bloqueios -----------------------------------------------------------------------


def test_block_removes_every_overlapping_slot():
    block = BlockSpec(RES_A, local(DAY, 10, 15), local(DAY, 10, 45))
    slots = hhmm(slots_for_day(make_ctx(blocks=[block]), DAY, RES_A))
    assert slots == ["09:00", "09:30", "11:00", "11:30"]


def test_block_touching_the_edge_does_not_remove_the_slot():
    block = BlockSpec(RES_A, local(DAY, 10, 0), local(DAY, 10, 30))
    slots = hhmm(slots_for_day(make_ctx(blocks=[block]), DAY, RES_A))
    assert "09:30" in slots and "10:30" in slots
    assert "10:00" not in slots


def test_tenant_wide_block_applies_to_every_resource():
    weekly = [
        WeeklyWindow(RES_A, TUESDAY, time(9), time(12)),
        WeeklyWindow(RES_B, TUESDAY, time(9), time(12)),
    ]
    block = BlockSpec(None, local(DAY, 9), local(DAY, 12))
    ctx = make_ctx(weekly=weekly, blocks=[block])
    assert slots_for_day(ctx, DAY, RES_A) == []
    assert slots_for_day(ctx, DAY, RES_B) == []


def test_block_of_another_resource_is_ignored():
    block = BlockSpec(RES_B, local(DAY, 9), local(DAY, 12))
    assert len(slots_for_day(make_ctx(blocks=[block]), DAY, RES_A)) == 6


# --- Agendamentos e buffer -----------------------------------------------------------


def test_booking_removes_its_slot():
    ctx = make_ctx(bookings=[booking(local(DAY, 10))])
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["09:00", "09:30", "10:30", "11:00", "11:30"]


def test_buffer_protects_both_sides_of_an_existing_booking():
    # Atendimento 10:00-10:30 com buffer de 10 min ocupa o recurso ate 10:40.
    # O candidato das 09:30 (ocupa ate 10:10) colide, o das 09:00 (ate 09:40) nao.
    ctx = make_ctx(buffer=10, bookings=[booking(local(DAY, 10), buffer=10)])
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["09:00", "11:00", "11:30"]


def test_cancelled_booking_does_not_block():
    ctx = make_ctx(bookings=[booking(local(DAY, 10), status="cancelado")])
    assert "10:00" in hhmm(slots_for_day(ctx, DAY, RES_A))


def test_booking_of_another_resource_does_not_block():
    ctx = make_ctx(bookings=[booking(local(DAY, 10), resource=RES_B)])
    assert "10:00" in hhmm(slots_for_day(ctx, DAY, RES_A))


def test_booking_of_a_different_service_blocks_the_resource():
    other = booking(local(DAY, 10), service_id=uuid4())
    assert "10:00" not in hhmm(slots_for_day(make_ctx(bookings=[other]), DAY, RES_A))


# --- Antecedencia minima e maxima ----------------------------------------------------


def test_min_notice_hides_slots_that_are_too_soon():
    now = local(DAY, 9, 50)
    ctx = make_ctx(now=now, min_notice=60)
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["11:00", "11:30"]


def test_past_day_has_no_slots():
    ctx = make_ctx(now=local(DAY + timedelta(days=1), 8))
    assert slots_for_day(ctx, DAY, RES_A) == []


def test_max_advance_hides_days_beyond_the_limit():
    assert slots_for_day(make_ctx(max_advance=1), DAY, RES_A) == []


def test_max_advance_limit_is_inclusive_to_the_minute():
    # NOW + 2 dias = 03/11 as 09:00 locais (12:00 UTC): so o primeiro horario cabe.
    ctx = make_ctx(max_advance=2)
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["09:00"]


# --- Capacidade (turmas) ------------------------------------------------------------


def test_group_service_reports_remaining_seats():
    group = [booking(local(DAY, 10), minutes=60, is_exclusive=False) for _ in range(2)]
    ctx = make_ctx(duration=60, capacity=3, bookings=group)
    by_time = {
        s.start.astimezone(SP).strftime("%H:%M"): s.remaining
        for s in slots_for_day(ctx, DAY, RES_A)
    }
    assert by_time == {"09:00": 3, "10:00": 1, "11:00": 3}


def test_group_service_disappears_when_full():
    group = [booking(local(DAY, 10), minutes=60, is_exclusive=False) for _ in range(3)]
    ctx = make_ctx(duration=60, capacity=3, bookings=group)
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["09:00", "11:00"]


def test_exclusive_booking_of_another_service_blocks_a_group_slot():
    intruder = booking(local(DAY, 10, 30), service_id=uuid4())
    ctx = make_ctx(duration=60, capacity=3, bookings=[intruder])
    # 10:00-11:00 colide com 10:30-11:00; 11:00-12:00 so encosta no fim do outro e segue livre.
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["09:00", "11:00"]


def test_group_booking_blocks_an_individual_service():
    group = booking(local(DAY, 10), minutes=60, is_exclusive=False, service_id=uuid4())
    ctx = make_ctx(duration=30, bookings=[group])
    assert hhmm(slots_for_day(ctx, DAY, RES_A)) == ["09:00", "09:30", "11:00", "11:30"]


# --- Fuso horario, horario de verao e virada de dia ------------------------------------


def test_slots_stay_on_the_local_day_when_utc_rolls_over():
    ctx = make_ctx(weekly=[WeeklyWindow(RES_A, TUESDAY, time(20), time(23, 30))])
    slots = slots_for_day(ctx, DAY, RES_A)
    assert hhmm(slots)[0] == "20:00" and hhmm(slots)[-1] == "23:00"
    last = slots[-1].start
    assert last.date() == date(2026, 11, 4)  # 23:00 em Sao Paulo = 02:00 UTC do dia seguinte
    assert last.astimezone(SP).date() == DAY
    assert slots_for_day(ctx, DAY + timedelta(days=1), RES_A) == []


def test_fall_back_day_has_one_extra_hour():
    day = date(2026, 11, 1)  # domingo, o relogio volta 1h em Nova York
    ctx = make_ctx(
        weekly=[WeeklyWindow(RES_A, 6, time(0), time(6))],
        duration=60,
        tz=NY,
        now=datetime(2026, 1, 1, tzinfo=UTC),
        max_advance=400,
    )
    slots = slots_for_day(ctx, day, RES_A)
    assert len(slots) == 7
    assert slots[-1].end - slots[0].start == timedelta(hours=7)


def test_spring_forward_day_has_one_hour_less():
    day = date(2026, 3, 8)  # domingo, o relogio avanca 1h em Nova York
    ctx = make_ctx(
        weekly=[WeeklyWindow(RES_A, 6, time(0), time(6))],
        duration=60,
        tz=NY,
        now=datetime(2026, 1, 1, tzinfo=UTC),
        max_advance=400,
    )
    assert len(slots_for_day(ctx, day, RES_A)) == 5


# --- Varios recursos e dias disponiveis -----------------------------------------------


@pytest.fixture
def two_resources() -> dict:
    return {
        "weekly": [
            WeeklyWindow(RES_A, TUESDAY, time(9), time(12)),
            WeeklyWindow(RES_B, TUESDAY, time(9), time(12)),
        ]
    }


def test_service_slots_list_free_resources_in_given_order(two_resources):
    ctx = make_ctx(**two_resources)
    slots = slots_for_service(ctx, DAY, [RES_A, RES_B])
    assert len(slots) == 6
    assert slots[0].resource_ids == (RES_A, RES_B)
    assert slots[0].default_resource_id == RES_A
    assert slots[0].remaining == 2


def test_service_slot_survives_while_one_resource_is_free(two_resources):
    ctx = make_ctx(**two_resources, bookings=[booking(local(DAY, 10), resource=RES_A)])
    ten = next(s for s in slots_for_service(ctx, DAY, [RES_A, RES_B]) if s.start == local(DAY, 10))
    assert ten.resource_ids == (RES_B,)
    assert ten.default_resource_id == RES_B


def test_service_slot_disappears_when_all_resources_are_taken(two_resources):
    taken = [booking(local(DAY, 10), resource=RES_A), booking(local(DAY, 10), resource=RES_B)]
    ctx = make_ctx(**two_resources, bookings=taken)
    starts = [s.start for s in slots_for_service(ctx, DAY, [RES_A, RES_B])]
    assert local(DAY, 10) not in starts


def test_available_days_lists_only_days_with_free_slots():
    ctx = make_ctx(
        weekly=[
            WeeklyWindow(RES_A, 1, time(9), time(12)),  # terca
            WeeklyWindow(RES_A, 3, time(9), time(12)),  # quinta
        ],
        exceptions=[DateExceptionSpec(None, date(2026, 11, 10), "closed")],
    )
    days = available_days(ctx, date(2026, 11, 2), date(2026, 11, 12), [RES_A])
    assert days == [date(2026, 11, 3), date(2026, 11, 5), date(2026, 11, 12)]

"""Motor de calculo de horarios livres.

Funcoes puras: recebem dados ja carregados (dataclasses simples, sem ORM nem banco) e
devolvem os horarios disponiveis. Isso permite testar todas as regras sem PostgreSQL.

Regras, em ordem de aplicacao, para uma data local do tenant e um recurso:

1. Janelas do dia
   - Excecao 'closed' (do recurso ou do tenant inteiro) fecha o dia.
   - Excecoes 'custom_hours' substituem a regra semanal. As do proprio recurso tem
     prioridade sobre as validas para todo o tenant.
   - No modo 'open_dates' do tenant, dias sem 'custom_hours' ficam sem horarios.
   - Caso contrario vale a regra semanal do dia da semana (0 = segunda).
2. Candidatos: a partir do inicio de cada janela, de `step` em `step` minutos, enquanto o
   atendimento inteiro couber na janela. Os calculos sao feitos em UTC, somando duracoes
   reais, entao dias com mudanca de horario de verao ficam corretos.
3. Filtros sobre cada candidato:
   - antecedencia minima e maxima;
   - bloqueios pontuais (so o atendimento, sem o buffer);
   - agendamentos ativos: o intervalo ocupado do candidato (atendimento + buffer) nao pode
     se sobrepor ao intervalo ocupado de outro agendamento, a mesma semantica da
     constraint de exclusao do banco. Servicos com capacidade maior que 1 aceitam varios
     agendamentos de turma no mesmo inicio, ate o limite de vagas.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

CANCELLED_STATUS = "cancelado"


@dataclass(frozen=True, slots=True)
class TenantRules:
    timezone: ZoneInfo
    availability_mode: str = "rules"  # 'rules' ou 'open_dates'
    min_notice_minutes: int = 60
    max_advance_days: int = 60


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    id: UUID
    duration_minutes: int
    buffer_minutes: int = 0
    capacity: int = 1
    slot_interval_minutes: int | None = None

    @property
    def step_minutes(self) -> int:
        """Distancia entre os inicios dos horarios. Nulo ou 0 = igual a duracao do servico."""
        return self.slot_interval_minutes or self.duration_minutes


@dataclass(frozen=True, slots=True)
class WeeklyWindow:
    resource_id: UUID
    weekday: int
    start: time
    end: time


@dataclass(frozen=True, slots=True)
class DateExceptionSpec:
    resource_id: UUID | None
    date: date
    kind: str  # 'closed' ou 'custom_hours'
    start: time | None = None
    end: time | None = None


@dataclass(frozen=True, slots=True)
class BlockSpec:
    resource_id: UUID | None
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True, slots=True)
class BookingSpec:
    resource_id: UUID
    service_id: UUID
    start_at: datetime
    occupied_until: datetime
    is_exclusive: bool = True
    status: str = "confirmado"


@dataclass(frozen=True, slots=True)
class SlotContext:
    """Tudo o que o calculo precisa saber, ja carregado."""

    tenant: TenantRules
    service: ServiceSpec
    now: datetime
    weekly: Sequence[WeeklyWindow] = ()
    exceptions: Sequence[DateExceptionSpec] = ()
    blocks: Sequence[BlockSpec] = ()
    bookings: Sequence[BookingSpec] = ()


@dataclass(frozen=True, slots=True)
class Slot:
    start: datetime  # UTC
    end: datetime  # UTC, fim do atendimento (sem o buffer)
    resource_id: UUID
    remaining: int  # vagas livres (1 para atendimento individual)


@dataclass(frozen=True, slots=True)
class ServiceSlot:
    """Horario do servico somando todos os recursos que podem atender nele."""

    start: datetime
    end: datetime
    resource_ids: tuple[UUID, ...]  # na ordem em que os recursos foram informados
    remaining: int

    @property
    def default_resource_id(self) -> UUID:
        """Recurso atribuido quando o cliente nao escolhe: o primeiro livre."""
        return self.resource_ids[0]


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime sem fuso horario nao e aceito pelo motor de slots")
    return value.astimezone(UTC)


def _local_to_utc(day: date, at: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def _local_windows(ctx: SlotContext, day: date, resource_id: UUID) -> list[tuple[time, time]]:
    todays = [e for e in ctx.exceptions if e.date == day and e.resource_id in (None, resource_id)]
    if any(e.kind == "closed" for e in todays):
        return []

    custom = [e for e in todays if e.kind == "custom_hours"]
    chosen = [e for e in custom if e.resource_id == resource_id] or custom
    if chosen:
        return [(e.start, e.end) for e in chosen if e.start is not None and e.end is not None]

    if ctx.tenant.availability_mode == "open_dates":
        return []

    return [
        (w.start, w.end)
        for w in ctx.weekly
        if w.resource_id == resource_id and w.weekday == day.weekday()
    ]


def _merge(intervals: Iterable[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _day_windows_utc(
    ctx: SlotContext, day: date, resource_id: UUID
) -> list[tuple[datetime, datetime]]:
    tz = ctx.tenant.timezone
    windows = [
        (_local_to_utc(day, start, tz), _local_to_utc(day, end, tz))
        for start, end in _local_windows(ctx, day, resource_id)
        if end > start
    ]
    return _merge(windows)


def slots_for_day(ctx: SlotContext, day: date, resource_id: UUID) -> list[Slot]:
    """Horarios livres de um recurso em uma data local do tenant, ordenados por inicio."""
    now = _to_utc(ctx.now)
    earliest = now + timedelta(minutes=ctx.tenant.min_notice_minutes)
    latest = now + timedelta(days=ctx.tenant.max_advance_days)

    service = ctx.service
    duration = timedelta(minutes=service.duration_minutes)
    buffer = timedelta(minutes=service.buffer_minutes)
    step = timedelta(minutes=service.step_minutes)

    blocks = [
        (_to_utc(b.start_at), _to_utc(b.end_at))
        for b in ctx.blocks
        if b.resource_id in (None, resource_id)
    ]
    bookings = [
        (_to_utc(b.start_at), _to_utc(b.occupied_until), b)
        for b in ctx.bookings
        if b.resource_id == resource_id and b.status != CANCELLED_STATUS
    ]

    slots: list[Slot] = []
    for window_start, window_end in _day_windows_utc(ctx, day, resource_id):
        start = window_start
        while start + duration <= window_end:
            end = start + duration
            if earliest <= start <= latest:
                remaining = _remaining_capacity(service, start, end, end + buffer, blocks, bookings)
                if remaining > 0:
                    slots.append(Slot(start, end, resource_id, remaining))
            start += step
    return slots


def _remaining_capacity(
    service: ServiceSpec,
    start: datetime,
    end: datetime,
    occupied_until: datetime,
    blocks: Sequence[tuple[datetime, datetime]],
    bookings: Sequence[tuple[datetime, datetime, BookingSpec]],
) -> int:
    """Vagas livres do candidato. 0 significa indisponivel."""
    if any(_overlaps(start, end, b_start, b_end) for b_start, b_end in blocks):
        return 0

    taken = 0
    for b_start, b_occupied_until, booking in bookings:
        if not _overlaps(start, occupied_until, b_start, b_occupied_until):
            continue
        same_group = (
            service.capacity > 1
            and not booking.is_exclusive
            and booking.service_id == service.id
            and b_start == start
        )
        if not same_group:
            return 0
        taken += 1
    return max(service.capacity - taken, 0)


def slots_for_service(
    ctx: SlotContext, day: date, resource_ids: Sequence[UUID]
) -> list[ServiceSlot]:
    """Une os horarios de varios recursos: cada inicio aparece uma vez, com os recursos livres."""
    by_start: dict[datetime, list[Slot]] = {}
    for resource_id in resource_ids:
        for slot in slots_for_day(ctx, day, resource_id):
            by_start.setdefault(slot.start, []).append(slot)

    return [
        ServiceSlot(
            start=start,
            end=group[0].end,
            resource_ids=tuple(s.resource_id for s in group),
            remaining=sum(s.remaining for s in group),
        )
        for start, group in sorted(by_start.items())
    ]


def available_days(
    ctx: SlotContext, first_day: date, last_day: date, resource_ids: Sequence[UUID]
) -> list[date]:
    """Datas locais, entre first_day e last_day (inclusive), com ao menos um horario livre."""
    days: list[date] = []
    current = first_day
    while current <= last_day:
        if slots_for_service(ctx, current, resource_ids):
            days.append(current)
        current += timedelta(days=1)
    return days

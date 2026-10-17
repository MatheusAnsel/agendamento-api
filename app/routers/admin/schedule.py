from datetime import date
from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy import delete, select

from app.core.errors import AppError
from app.deps import CurrentAdmin, SessionDep
from app.models import Block, DateException, WeeklyRule
from app.routers.admin.catalog import _get_resource
from app.schemas.manage import (
    BlockIn,
    BlockOut,
    DateExceptionIn,
    DateExceptionOut,
    WeeklyRuleOut,
    WeeklyRulesIn,
)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


async def _check_optional_resource(session, tenant_id: UUID, resource_id: UUID | None) -> None:
    if resource_id is not None:
        await _get_resource(session, tenant_id, resource_id)


# ---------- horario semanal ----------


@router.get("/resources/{resource_id}/weekly-rules", response_model=list[WeeklyRuleOut])
async def list_weekly_rules(
    resource_id: UUID, admin: CurrentAdmin, session: SessionDep
) -> list[WeeklyRule]:
    await _get_resource(session, admin.tenant_id, resource_id)
    return list(
        (
            await session.execute(
                select(WeeklyRule)
                .where(
                    WeeklyRule.tenant_id == admin.tenant_id, WeeklyRule.resource_id == resource_id
                )
                .order_by(WeeklyRule.weekday, WeeklyRule.start_time)
            )
        ).scalars()
    )


@router.put("/resources/{resource_id}/weekly-rules", response_model=list[WeeklyRuleOut])
async def replace_weekly_rules(
    resource_id: UUID, data: WeeklyRulesIn, admin: CurrentAdmin, session: SessionDep
) -> list[WeeklyRule]:
    """Substitui o horario semanal inteiro do profissional pela lista enviada."""
    await _get_resource(session, admin.tenant_id, resource_id)
    await session.execute(
        delete(WeeklyRule).where(
            WeeklyRule.tenant_id == admin.tenant_id, WeeklyRule.resource_id == resource_id
        )
    )
    rules = [
        WeeklyRule(
            tenant_id=admin.tenant_id,
            resource_id=resource_id,
            weekday=r.weekday,
            start_time=r.start_time,
            end_time=r.end_time,
        )
        for r in data.rules
    ]
    session.add_all(rules)
    await session.commit()
    return sorted(rules, key=lambda r: (r.weekday, r.start_time))


# ---------- excecoes por data ----------


@router.get("/date-exceptions", response_model=list[DateExceptionOut])
async def list_exceptions(
    admin: CurrentAdmin,
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DateException]:
    query = select(DateException).where(DateException.tenant_id == admin.tenant_id)
    if date_from:
        query = query.where(DateException.date >= date_from)
    if date_to:
        query = query.where(DateException.date <= date_to)
    return list((await session.execute(query.order_by(DateException.date))).scalars())


@router.post(
    "/date-exceptions", response_model=DateExceptionOut, status_code=status.HTTP_201_CREATED
)
async def create_exception(
    data: DateExceptionIn, admin: CurrentAdmin, session: SessionDep
) -> DateException:
    await _check_optional_resource(session, admin.tenant_id, data.resource_id)
    item = DateException(
        tenant_id=admin.tenant_id,
        resource_id=data.resource_id,
        date=data.date,
        kind=data.kind,
        start_time=data.start_time,
        end_time=data.end_time,
        reason=data.reason,
    )
    session.add(item)
    await session.commit()
    return item


@router.delete("/date-exceptions/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exception(item_id: UUID, admin: CurrentAdmin, session: SessionDep) -> None:
    item = await session.get(DateException, item_id)
    if item is None or item.tenant_id != admin.tenant_id:
        raise AppError(404, "not_found", "Excecao nao encontrada")
    await session.delete(item)
    await session.commit()


# ---------- bloqueios ----------


@router.get("/blocks", response_model=list[BlockOut])
async def list_blocks(admin: CurrentAdmin, session: SessionDep) -> list[Block]:
    return list(
        (
            await session.execute(
                select(Block).where(Block.tenant_id == admin.tenant_id).order_by(Block.start_at)
            )
        ).scalars()
    )


@router.post("/blocks", response_model=BlockOut, status_code=status.HTTP_201_CREATED)
async def create_block(data: BlockIn, admin: CurrentAdmin, session: SessionDep) -> Block:
    await _check_optional_resource(session, admin.tenant_id, data.resource_id)
    block = Block(
        tenant_id=admin.tenant_id,
        resource_id=data.resource_id,
        start_at=data.start_at,
        end_at=data.end_at,
        reason=data.reason,
    )
    session.add(block)
    await session.commit()
    return block


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block(block_id: UUID, admin: CurrentAdmin, session: SessionDep) -> None:
    block = await session.get(Block, block_id)
    if block is None or block.tenant_id != admin.tenant_id:
        raise AppError(404, "not_found", "Bloqueio nao encontrado")
    await session.delete(block)
    await session.commit()

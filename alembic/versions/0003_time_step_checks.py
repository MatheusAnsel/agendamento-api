"""duracao, intervalo e buffer em multiplos de 10 minutos

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17 19:20:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STEP = 10


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_services_duration_step"), "services", f"mod(duration_minutes, {STEP}) = 0"
    )
    op.create_check_constraint(
        op.f("ck_services_buffer_step"), "services", f"mod(buffer_minutes, {STEP}) = 0"
    )
    op.create_check_constraint(
        op.f("ck_services_slot_interval_step"),
        "services",
        f"slot_interval_minutes IS NULL OR mod(slot_interval_minutes, {STEP}) = 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_services_slot_interval_step"), "services", type_="check")
    op.drop_constraint(op.f("ck_services_buffer_step"), "services", type_="check")
    op.drop_constraint(op.f("ck_services_duration_step"), "services", type_="check")

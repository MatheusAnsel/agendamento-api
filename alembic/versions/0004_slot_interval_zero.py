"""intervalo entre inicios aceita 0 (igual a duracao)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17 19:35:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_services_slot_interval_positive"), "services", type_="check")
    op.create_check_constraint(
        op.f("ck_services_slot_interval_non_negative"),
        "services",
        "slot_interval_minutes IS NULL OR slot_interval_minutes >= 0",
    )


def downgrade() -> None:
    # 0 significava "igual a duracao", o mesmo que nulo.
    op.execute("UPDATE services SET slot_interval_minutes = NULL WHERE slot_interval_minutes = 0")
    op.drop_constraint(op.f("ck_services_slot_interval_non_negative"), "services", type_="check")
    op.create_check_constraint(
        op.f("ck_services_slot_interval_positive"),
        "services",
        "slot_interval_minutes IS NULL OR slot_interval_minutes > 0",
    )

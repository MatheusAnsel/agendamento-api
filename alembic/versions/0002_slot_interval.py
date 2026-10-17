"""intervalo entre inicios de slot por servico

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17 19:05:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("services", sa.Column("slot_interval_minutes", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_services_slot_interval_positive"),
        "services",
        "slot_interval_minutes IS NULL OR slot_interval_minutes > 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_services_slot_interval_positive"), "services", type_="check")
    op.drop_column("services", "slot_interval_minutes")

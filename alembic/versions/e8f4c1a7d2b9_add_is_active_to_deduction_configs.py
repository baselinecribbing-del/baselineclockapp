"""add is_active to deduction_configs

Revision ID: e8f4c1a7d2b9
Revises: d9f1c3a4b5e6
Create Date: 2026-03-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8f4c1a7d2b9"
down_revision: Union[str, Sequence[str], None] = "d9f1c3a4b5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deduction_configs",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_deduction_configs_is_active", "deduction_configs", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_deduction_configs_is_active", table_name="deduction_configs")
    op.drop_column("deduction_configs", "is_active")

"""add calculation_source to payroll_deductions

Revision ID: f0a1b2c3d4e5
Revises: e8f4c1a7d2b9
Create Date: 2026-03-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e8f4c1a7d2b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payroll_deductions",
        sa.Column(
            "calculation_source",
            sa.String(),
            nullable=False,
            server_default=sa.text("'CONFIG'"),
        ),
    )
    op.create_check_constraint(
        "ck_payroll_deductions_calculation_source_known",
        "payroll_deductions",
        "calculation_source IN ('CONFIG', 'STATUTORY')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payroll_deductions_calculation_source_known",
        "payroll_deductions",
        type_="check",
    )
    op.drop_column("payroll_deductions", "calculation_source")

"""add payroll run supersession fields

Revision ID: 0f1e2d3c4b5a
Revises: e6f7a8b9c0d1
Create Date: 2026-03-14 02:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0f1e2d3c4b5a"
down_revision: Union[str, Sequence[str], None] = "e9a1b2c3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_run", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_run", sa.Column("superseded_by_user_id", sa.String(), nullable=True))
    op.add_column("payroll_run", sa.Column("superseded_by_payroll_run_id", sa.String(), nullable=True))
    op.add_column("payroll_run", sa.Column("correction_reason", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_payroll_run_superseded_by_payroll_run_id_payroll_run",
        "payroll_run",
        "payroll_run",
        ["superseded_by_payroll_run_id"],
        ["payroll_run_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_payroll_run_superseded_by_payroll_run_id_payroll_run", "payroll_run", type_="foreignkey")
    op.drop_column("payroll_run", "correction_reason")
    op.drop_column("payroll_run", "superseded_by_payroll_run_id")
    op.drop_column("payroll_run", "superseded_by_user_id")
    op.drop_column("payroll_run", "superseded_at")

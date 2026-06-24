"""add remittance ops fields

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-03-14 01:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_remittance_obligations", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("payroll_remittance_obligations", sa.Column("remittance_period_label", sa.String(), nullable=True))
    op.add_column("payroll_remittance_obligations", sa.Column("reference_note", sa.String(), nullable=True))
    op.add_column("payroll_remittance_obligations", sa.Column("remitted_reference", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("payroll_remittance_obligations", "remitted_reference")
    op.drop_column("payroll_remittance_obligations", "reference_note")
    op.drop_column("payroll_remittance_obligations", "remittance_period_label")
    op.drop_column("payroll_remittance_obligations", "due_date")

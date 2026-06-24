"""harden payroll run supersession integrity

Revision ID: 1a2b3c4d5e6f
Revises: 0f1e2d3c4b5a
Create Date: 2026-03-13 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "0f1e2d3c4b5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_payroll_run_supersession_state_coherent",
        "payroll_run",
        "("
        "superseded_at IS NULL "
        "AND superseded_by_user_id IS NULL "
        "AND superseded_by_payroll_run_id IS NULL "
        "AND correction_reason IS NULL"
        ") OR ("
        "superseded_at IS NOT NULL "
        "AND status = 'FINALIZED' "
        "AND superseded_by_user_id IS NOT NULL "
        "AND btrim(superseded_by_user_id) <> '' "
        "AND correction_reason IS NOT NULL "
        "AND btrim(correction_reason) <> ''"
        ")",
    )
    op.create_check_constraint(
        "ck_payroll_run_superseded_not_self_reference",
        "payroll_run",
        "superseded_by_payroll_run_id IS NULL OR superseded_by_payroll_run_id <> payroll_run_id",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payroll_run_superseded_not_self_reference", "payroll_run", type_="check")
    op.drop_constraint("ck_payroll_run_supersession_state_coherent", "payroll_run", type_="check")

"""add paystubs table

Revision ID: e1f6a9b3c4d5
Revises: d4a8f1c2b7e3
Create Date: 2026-03-06 17:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f6a9b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d4a8f1c2b7e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paystubs",
        sa.Column("paystub_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("payroll_run_id", sa.String(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("gross_pay_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["payroll_run_id"],
            ["payroll_run.payroll_run_id"],
            ondelete="RESTRICT",
            name="fk_paystubs_payroll_run_id_payroll_run",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
            name="fk_paystubs_employee_id_employees",
        ),
        sa.PrimaryKeyConstraint("paystub_id"),
        sa.UniqueConstraint(
            "company_id",
            "payroll_run_id",
            "employee_id",
            name="uq_paystubs_company_run_employee",
        ),
        sa.CheckConstraint("gross_pay_cents >= 0", name="ck_paystubs_gross_pay_cents_nonnegative"),
    )

    op.create_index("ix_paystubs_company_id", "paystubs", ["company_id"], unique=False)
    op.create_index("ix_paystubs_payroll_run_id", "paystubs", ["payroll_run_id"], unique=False)
    op.create_index("ix_paystubs_employee_id", "paystubs", ["employee_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_paystubs_employee_id", table_name="paystubs")
    op.drop_index("ix_paystubs_payroll_run_id", table_name="paystubs")
    op.drop_index("ix_paystubs_company_id", table_name="paystubs")
    op.drop_table("paystubs")

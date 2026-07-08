"""add payroll t4s table

Revision ID: e5f6a7b8c9d0
Revises: d6e4f2a1b3c7
Create Date: 2026-03-13 11:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d6e4f2a1b3c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_t4s",
        sa.Column("t4_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("employment_income_cents", sa.Integer(), nullable=False),
        sa.Column("cpp_contributions_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ei_premiums_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("income_tax_deducted_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("other_deductions_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("slip_status", sa.String(), nullable=False, server_default="RECORD_ONLY"),
        sa.Column("slip_storage_key", sa.String(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("generated_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
            name="fk_payroll_t4s_employee_id_employees",
        ),
        sa.PrimaryKeyConstraint("t4_id"),
        sa.UniqueConstraint("company_id", "employee_id", "tax_year", name="uq_payroll_t4s_company_employee_year"),
        sa.CheckConstraint("tax_year >= 2000", name="ck_payroll_t4s_tax_year_min"),
        sa.CheckConstraint("employment_income_cents >= 0", name="ck_payroll_t4s_income_nonnegative"),
        sa.CheckConstraint("cpp_contributions_cents >= 0", name="ck_payroll_t4s_cpp_nonnegative"),
        sa.CheckConstraint("ei_premiums_cents >= 0", name="ck_payroll_t4s_ei_nonnegative"),
        sa.CheckConstraint("income_tax_deducted_cents >= 0", name="ck_payroll_t4s_income_tax_nonnegative"),
        sa.CheckConstraint("other_deductions_cents >= 0", name="ck_payroll_t4s_other_deductions_nonnegative"),
        sa.CheckConstraint("slip_status IN ('RECORD_ONLY', 'AVAILABLE')", name="ck_payroll_t4s_slip_status_valid"),
        sa.CheckConstraint(
            "(slip_status <> 'AVAILABLE') OR (slip_storage_key IS NOT NULL)",
            name="ck_payroll_t4s_available_requires_storage_key",
        ),
    )

    op.create_index("ix_payroll_t4s_company_id", "payroll_t4s", ["company_id"], unique=False)
    op.create_index("ix_payroll_t4s_employee_id", "payroll_t4s", ["employee_id"], unique=False)
    op.create_index("ix_payroll_t4s_tax_year", "payroll_t4s", ["tax_year"], unique=False)
    op.create_index("ix_payroll_t4s_slip_status", "payroll_t4s", ["slip_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_payroll_t4s_slip_status", table_name="payroll_t4s")
    op.drop_index("ix_payroll_t4s_tax_year", table_name="payroll_t4s")
    op.drop_index("ix_payroll_t4s_employee_id", table_name="payroll_t4s")
    op.drop_index("ix_payroll_t4s_company_id", table_name="payroll_t4s")
    op.drop_table("payroll_t4s")

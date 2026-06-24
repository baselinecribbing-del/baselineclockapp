"""add payroll remittance obligations

Revision ID: c4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-13 21:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_remittance_obligations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("payroll_run_id", sa.String(), nullable=False),
        sa.Column("remittance_type", sa.String(), nullable=False, server_default="SOURCE_DEDUCTIONS"),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("tax_month", sa.Integer(), nullable=False),
        sa.Column("employee_deductions_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("employer_contributions_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_remittance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(), nullable=False, server_default="CAD"),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("marked_remitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("marked_remitted_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["payroll_run_id"],
            ["payroll_run.payroll_run_id"],
            name="fk_payroll_remittance_obligations_payroll_run_id_payroll_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "payroll_run_id",
            name="uq_payroll_remittance_obligations_company_run",
        ),
        sa.CheckConstraint(
            "tax_year >= 2000",
            name="ck_payroll_remittance_obligations_tax_year_min",
        ),
        sa.CheckConstraint(
            "tax_month >= 1 AND tax_month <= 12",
            name="ck_payroll_remittance_obligations_tax_month_range",
        ),
        sa.CheckConstraint(
            "employee_deductions_cents >= 0",
            name="ck_payroll_remit_oblig_emp_ded_nonneg",
        ),
        sa.CheckConstraint(
            "employer_contributions_cents >= 0",
            name="ck_payroll_remit_oblig_empr_contrib_nonneg",
        ),
        sa.CheckConstraint(
            "total_remittance_cents >= 0",
            name="ck_payroll_remit_oblig_total_nonneg",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'REMITTED_MANUAL')",
            name="ck_payroll_remittance_obligations_status_valid",
        ),
        sa.CheckConstraint(
            "remittance_type IN ('SOURCE_DEDUCTIONS')",
            name="ck_payroll_remittance_obligations_type_valid",
        ),
        sa.CheckConstraint(
            "currency IN ('CAD')",
            name="ck_payroll_remittance_obligations_currency_valid",
        ),
        sa.CheckConstraint(
            "(status <> 'REMITTED_MANUAL') OR (marked_remitted_at IS NOT NULL AND marked_remitted_by_user_id IS NOT NULL)",
            name="ck_payroll_remit_oblig_remitted_has_actor",
        ),
    )
    op.create_index(
        "ix_payroll_remittance_obligations_company_id",
        "payroll_remittance_obligations",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_payroll_remittance_obligations_payroll_run_id",
        "payroll_remittance_obligations",
        ["payroll_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_payroll_remittance_obligations_status",
        "payroll_remittance_obligations",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_remittance_obligations_status", table_name="payroll_remittance_obligations")
    op.drop_index("ix_payroll_remittance_obligations_payroll_run_id", table_name="payroll_remittance_obligations")
    op.drop_index("ix_payroll_remittance_obligations_company_id", table_name="payroll_remittance_obligations")
    op.drop_table("payroll_remittance_obligations")

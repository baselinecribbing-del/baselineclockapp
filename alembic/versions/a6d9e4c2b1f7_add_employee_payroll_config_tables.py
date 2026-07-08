"""add employee payroll config tables

Revision ID: a6d9e4c2b1f7
Revises: a4b7c9d2e1f3
Create Date: 2026-03-10 17:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a6d9e4c2b1f7"
down_revision: Union[str, Sequence[str], None] = "a4b7c9d2e1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vacation_policies",
        sa.Column("vacation_policy_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("accrual_rate_percent", sa.Numeric(7, 4), nullable=True),
        sa.Column("payout_rate_percent", sa.Numeric(7, 4), nullable=True),
        sa.Column("payout_method", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "((accrual_rate_percent IS NOT NULL AND payout_rate_percent IS NULL) OR "
            "(accrual_rate_percent IS NULL AND payout_rate_percent IS NOT NULL))",
            name="ck_vacation_policies_rate_xor_valid",
        ),
        sa.CheckConstraint(
            "accrual_rate_percent IS NULL OR accrual_rate_percent >= 0",
            name="ck_vacation_policies_accrual_rate_nonnegative",
        ),
        sa.CheckConstraint(
            "payout_rate_percent IS NULL OR payout_rate_percent >= 0",
            name="ck_vacation_policies_payout_rate_nonnegative",
        ),
        sa.CheckConstraint(
            "payout_method IN ('accrued','each_pay_period')",
            name="ck_vacation_policies_payout_method_valid",
        ),
        sa.PrimaryKeyConstraint("vacation_policy_id"),
    )
    op.create_index("ix_vacation_policies_company_id", "vacation_policies", ["company_id"], unique=False)
    op.create_index("ix_vacation_policies_is_active", "vacation_policies", ["is_active"], unique=False)
    op.create_index("ix_vacation_policies_payout_method", "vacation_policies", ["payout_method"], unique=False)

    op.create_table(
        "employee_vacation_assignments",
        sa.Column("assignment_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("vacation_policy_id", sa.String(), nullable=False),
        sa.Column("effective_start_date", sa.Date(), nullable=False),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("override_rate_percent", sa.Numeric(7, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "effective_end_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_employee_vacation_assignments_effective_dates_valid",
        ),
        sa.CheckConstraint(
            "override_rate_percent IS NULL OR override_rate_percent >= 0",
            name="ck_employee_vacation_assignments_override_rate_nonnegative",
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vacation_policy_id"], ["vacation_policies.vacation_policy_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("assignment_id"),
    )
    op.create_index("ix_employee_vacation_assignments_company_id", "employee_vacation_assignments", ["company_id"], unique=False)
    op.create_index("ix_employee_vacation_assignments_employee_id", "employee_vacation_assignments", ["employee_id"], unique=False)
    op.create_index(
        "ix_employee_vacation_assignments_vacation_policy_id",
        "employee_vacation_assignments",
        ["vacation_policy_id"],
        unique=False,
    )
    op.create_index(
        "ix_employee_vacation_assignments_effective_start_date",
        "employee_vacation_assignments",
        ["effective_start_date"],
        unique=False,
    )
    op.create_index(
        "ix_employee_vacation_assignments_effective_end_date",
        "employee_vacation_assignments",
        ["effective_end_date"],
        unique=False,
    )

    op.create_table(
        "employee_payroll_enrollments",
        sa.Column("enrollment_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("employee_amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("employer_amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("frequency", sa.String(length=64), nullable=False),
        sa.Column("effective_start_date", sa.Date(), nullable=False),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "category IN ('benefit','deduction')",
            name="ck_employee_payroll_enrollments_category_valid",
        ),
        sa.CheckConstraint(
            "employee_amount_cents >= 0",
            name="ck_employee_payroll_enrollments_employee_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "employer_amount_cents >= 0",
            name="ck_employee_payroll_enrollments_employer_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "effective_end_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_employee_payroll_enrollments_effective_dates_valid",
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("enrollment_id"),
    )
    op.create_index("ix_employee_payroll_enrollments_company_id", "employee_payroll_enrollments", ["company_id"], unique=False)
    op.create_index("ix_employee_payroll_enrollments_employee_id", "employee_payroll_enrollments", ["employee_id"], unique=False)
    op.create_index("ix_employee_payroll_enrollments_code", "employee_payroll_enrollments", ["code"], unique=False)
    op.create_index("ix_employee_payroll_enrollments_category", "employee_payroll_enrollments", ["category"], unique=False)
    op.create_index(
        "ix_employee_payroll_enrollments_effective_start_date",
        "employee_payroll_enrollments",
        ["effective_start_date"],
        unique=False,
    )
    op.create_index(
        "ix_employee_payroll_enrollments_effective_end_date",
        "employee_payroll_enrollments",
        ["effective_end_date"],
        unique=False,
    )
    op.create_index("ix_employee_payroll_enrollments_is_active", "employee_payroll_enrollments", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_employee_payroll_enrollments_is_active", table_name="employee_payroll_enrollments")
    op.drop_index("ix_employee_payroll_enrollments_effective_end_date", table_name="employee_payroll_enrollments")
    op.drop_index("ix_employee_payroll_enrollments_effective_start_date", table_name="employee_payroll_enrollments")
    op.drop_index("ix_employee_payroll_enrollments_category", table_name="employee_payroll_enrollments")
    op.drop_index("ix_employee_payroll_enrollments_code", table_name="employee_payroll_enrollments")
    op.drop_index("ix_employee_payroll_enrollments_employee_id", table_name="employee_payroll_enrollments")
    op.drop_index("ix_employee_payroll_enrollments_company_id", table_name="employee_payroll_enrollments")
    op.drop_table("employee_payroll_enrollments")

    op.drop_index("ix_employee_vacation_assignments_effective_end_date", table_name="employee_vacation_assignments")
    op.drop_index("ix_employee_vacation_assignments_effective_start_date", table_name="employee_vacation_assignments")
    op.drop_index("ix_employee_vacation_assignments_vacation_policy_id", table_name="employee_vacation_assignments")
    op.drop_index("ix_employee_vacation_assignments_employee_id", table_name="employee_vacation_assignments")
    op.drop_index("ix_employee_vacation_assignments_company_id", table_name="employee_vacation_assignments")
    op.drop_table("employee_vacation_assignments")

    op.drop_index("ix_vacation_policies_payout_method", table_name="vacation_policies")
    op.drop_index("ix_vacation_policies_is_active", table_name="vacation_policies")
    op.drop_index("ix_vacation_policies_company_id", table_name="vacation_policies")
    op.drop_table("vacation_policies")

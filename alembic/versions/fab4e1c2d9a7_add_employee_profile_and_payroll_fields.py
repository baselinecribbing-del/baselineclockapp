"""add employee profile and payroll fields

Revision ID: fab4e1c2d9a7
Revises: f9a0b1c2d3e4
Create Date: 2026-03-08 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fab4e1c2d9a7"
down_revision: Union[str, Sequence[str], None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("legal_name", sa.String(), nullable=True))
    op.add_column("employees", sa.Column("preferred_name", sa.String(), nullable=True))
    op.add_column("employees", sa.Column("phone", sa.String(), nullable=True))
    op.add_column("employees", sa.Column("email", sa.String(), nullable=True))
    op.add_column("employees", sa.Column("trade_type_id", sa.String(), nullable=True))
    op.add_column("employees", sa.Column("crew_name", sa.String(), nullable=True))
    op.add_column(
        "employees",
        sa.Column("pay_type", sa.String(), nullable=False, server_default="HOURLY"),
    )
    op.add_column("employees", sa.Column("salary_cents", sa.Integer(), nullable=True))
    op.add_column("employees", sa.Column("hire_date", sa.Date(), nullable=True))
    op.add_column("employees", sa.Column("emergency_contact_name", sa.String(), nullable=True))
    op.add_column("employees", sa.Column("emergency_contact_phone", sa.String(), nullable=True))
    op.add_column("employees", sa.Column("emergency_contact_relationship", sa.String(), nullable=True))
    op.add_column("employees", sa.Column("field_profile_notes", sa.String(), nullable=True))
    op.add_column("employees", sa.Column("documents_notes", sa.String(), nullable=True))

    op.execute("UPDATE employees SET legal_name = name WHERE legal_name IS NULL")

    op.create_index("ix_employees_pay_type", "employees", ["pay_type"], unique=False)
    op.create_index("ix_employees_trade_type_id", "employees", ["trade_type_id"], unique=False)

    op.drop_constraint("ck_employees_labor_class_valid", "employees", type_="check")
    op.create_check_constraint(
        "ck_employees_labor_class_valid",
        "employees",
        "labor_class IN ('PAYROLL_EMPLOYEE','CASUAL_CASH','CASUAL_LABOUR','SUBCONTRACTOR_HOURLY')",
    )
    op.create_check_constraint(
        "ck_employees_pay_type_valid",
        "employees",
        "pay_type IN ('HOURLY','SALARY')",
    )
    op.create_check_constraint(
        "ck_employees_salary_cents_nonnegative",
        "employees",
        "salary_cents IS NULL OR salary_cents >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_employees_salary_cents_nonnegative", "employees", type_="check")
    op.drop_constraint("ck_employees_pay_type_valid", "employees", type_="check")

    op.drop_constraint("ck_employees_labor_class_valid", "employees", type_="check")
    op.create_check_constraint(
        "ck_employees_labor_class_valid",
        "employees",
        "labor_class IN ('PAYROLL_EMPLOYEE','CASUAL_CASH','SUBCONTRACTOR_HOURLY')",
    )

    op.drop_index("ix_employees_trade_type_id", table_name="employees")
    op.drop_index("ix_employees_pay_type", table_name="employees")

    op.drop_column("employees", "documents_notes")
    op.drop_column("employees", "field_profile_notes")
    op.drop_column("employees", "emergency_contact_relationship")
    op.drop_column("employees", "emergency_contact_phone")
    op.drop_column("employees", "emergency_contact_name")
    op.drop_column("employees", "hire_date")
    op.drop_column("employees", "salary_cents")
    op.drop_column("employees", "pay_type")
    op.drop_column("employees", "crew_name")
    op.drop_column("employees", "trade_type_id")
    op.drop_column("employees", "email")
    op.drop_column("employees", "phone")
    op.drop_column("employees", "preferred_name")
    op.drop_column("employees", "legal_name")

"""add payroll grade employee master fields

Revision ID: 2c9d4e7f1a2b
Revises: fc1a2b3d4e5f
Create Date: 2026-03-09 09:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2c9d4e7f1a2b"
down_revision: Union[str, Sequence[str], None] = "fc1a2b3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in cols)


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = inspector.get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def _check_exists(table_name: str, check_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    checks = inspector.get_check_constraints(table_name)
    return any(chk["name"] == check_name for chk in checks)


def upgrade() -> None:
    if not _column_exists("employees", "legal_first_name"):
        op.add_column("employees", sa.Column("legal_first_name", sa.String(), nullable=True))
    if not _column_exists("employees", "legal_last_name"):
        op.add_column("employees", sa.Column("legal_last_name", sa.String(), nullable=True))
    if not _column_exists("employees", "birth_date"):
        op.add_column("employees", sa.Column("birth_date", sa.Date(), nullable=True))
    if not _column_exists("employees", "sin"):
        op.add_column("employees", sa.Column("sin", sa.String(length=32), nullable=True))

    if not _column_exists("employees", "address_line_1"):
        op.add_column("employees", sa.Column("address_line_1", sa.String(), nullable=True))
    if not _column_exists("employees", "address_line_2"):
        op.add_column("employees", sa.Column("address_line_2", sa.String(), nullable=True))
    if not _column_exists("employees", "city"):
        op.add_column("employees", sa.Column("city", sa.String(), nullable=True))
    if not _column_exists("employees", "province"):
        op.add_column("employees", sa.Column("province", sa.String(length=16), nullable=True))
    if not _column_exists("employees", "postal_code"):
        op.add_column("employees", sa.Column("postal_code", sa.String(length=16), nullable=True))
    if not _column_exists("employees", "country"):
        op.add_column("employees", sa.Column("country", sa.String(length=2), nullable=True))

    if not _column_exists("employees", "mailing_address_line_1"):
        op.add_column("employees", sa.Column("mailing_address_line_1", sa.String(), nullable=True))
    if not _column_exists("employees", "mailing_address_line_2"):
        op.add_column("employees", sa.Column("mailing_address_line_2", sa.String(), nullable=True))
    if not _column_exists("employees", "mailing_city"):
        op.add_column("employees", sa.Column("mailing_city", sa.String(), nullable=True))
    if not _column_exists("employees", "mailing_province"):
        op.add_column("employees", sa.Column("mailing_province", sa.String(length=16), nullable=True))
    if not _column_exists("employees", "mailing_postal_code"):
        op.add_column("employees", sa.Column("mailing_postal_code", sa.String(length=16), nullable=True))
    if not _column_exists("employees", "mailing_country"):
        op.add_column("employees", sa.Column("mailing_country", sa.String(length=2), nullable=True))

    if not _column_exists("employees", "employment_status"):
        op.add_column(
            "employees",
            sa.Column(
                "employment_status",
                sa.String(length=24),
                nullable=False,
                server_default="ACTIVE",
            ),
        )
    if not _column_exists("employees", "termination_date"):
        op.add_column("employees", sa.Column("termination_date", sa.Date(), nullable=True))
    if not _column_exists("employees", "work_location"):
        op.add_column("employees", sa.Column("work_location", sa.String(), nullable=True))
    if not _column_exists("employees", "manager_name"):
        op.add_column("employees", sa.Column("manager_name", sa.String(), nullable=True))
    if not _column_exists("employees", "department"):
        op.add_column("employees", sa.Column("department", sa.String(), nullable=True))
    if not _column_exists("employees", "job_title"):
        op.add_column("employees", sa.Column("job_title", sa.String(), nullable=True))
    if not _column_exists("employees", "employee_number"):
        op.add_column("employees", sa.Column("employee_number", sa.String(), nullable=True))
    if not _column_exists("employees", "pay_schedule"):
        op.add_column("employees", sa.Column("pay_schedule", sa.String(length=24), nullable=True))

    if not _column_exists("employees", "base_rate_cents"):
        op.add_column("employees", sa.Column("base_rate_cents", sa.Integer(), nullable=True))
    if not _column_exists("employees", "base_rate_effective_date"):
        op.add_column("employees", sa.Column("base_rate_effective_date", sa.Date(), nullable=True))
    if not _column_exists("employees", "payment_method"):
        op.add_column("employees", sa.Column("payment_method", sa.String(length=32), nullable=True))
    if not _column_exists("employees", "default_hours"):
        op.add_column("employees", sa.Column("default_hours", sa.Numeric(6, 2), nullable=True))

    if not _column_exists("employees", "province_of_employment"):
        op.add_column("employees", sa.Column("province_of_employment", sa.String(length=16), nullable=True))
    if not _column_exists("employees", "federal_claim_amount"):
        op.add_column("employees", sa.Column("federal_claim_amount", sa.Numeric(12, 2), nullable=True))
    if not _column_exists("employees", "provincial_claim_amount"):
        op.add_column("employees", sa.Column("provincial_claim_amount", sa.Numeric(12, 2), nullable=True))
    if not _column_exists("employees", "additional_tax_withholding"):
        op.add_column("employees", sa.Column("additional_tax_withholding", sa.Numeric(12, 2), nullable=True))
    if not _column_exists("employees", "tax_exemptions"):
        op.add_column("employees", sa.Column("tax_exemptions", sa.String(), nullable=True))

    if not _index_exists("employees", "ix_employees_employee_number"):
        op.create_index("ix_employees_employee_number", "employees", ["employee_number"], unique=False)
    if not _index_exists("employees", "ix_employees_employment_status"):
        op.create_index("ix_employees_employment_status", "employees", ["employment_status"], unique=False)

    if not _check_exists("employees", "ck_employees_employment_status_valid"):
        op.create_check_constraint(
            "ck_employees_employment_status_valid",
            "employees",
            "employment_status IN ('ACTIVE','ON_LEAVE','TERMINATED')",
        )
    if not _check_exists("employees", "ck_employees_default_hours_nonnegative"):
        op.create_check_constraint(
            "ck_employees_default_hours_nonnegative",
            "employees",
            "default_hours IS NULL OR default_hours >= 0",
        )
    if not _check_exists("employees", "ck_employees_base_rate_cents_nonnegative"):
        op.create_check_constraint(
            "ck_employees_base_rate_cents_nonnegative",
            "employees",
            "base_rate_cents IS NULL OR base_rate_cents >= 0",
        )
    if not _check_exists("employees", "ck_employees_federal_claim_amount_nonnegative"):
        op.create_check_constraint(
            "ck_employees_federal_claim_amount_nonnegative",
            "employees",
            "federal_claim_amount IS NULL OR federal_claim_amount >= 0",
        )
    if not _check_exists("employees", "ck_employees_provincial_claim_amount_nonnegative"):
        op.create_check_constraint(
            "ck_employees_provincial_claim_amount_nonnegative",
            "employees",
            "provincial_claim_amount IS NULL OR provincial_claim_amount >= 0",
        )
    if not _check_exists("employees", "ck_employees_additional_tax_withholding_nonnegative"):
        op.create_check_constraint(
            "ck_employees_additional_tax_withholding_nonnegative",
            "employees",
            "additional_tax_withholding IS NULL OR additional_tax_withholding >= 0",
        )


def downgrade() -> None:
    if _check_exists("employees", "ck_employees_additional_tax_withholding_nonnegative"):
        op.drop_constraint("ck_employees_additional_tax_withholding_nonnegative", "employees", type_="check")
    if _check_exists("employees", "ck_employees_provincial_claim_amount_nonnegative"):
        op.drop_constraint("ck_employees_provincial_claim_amount_nonnegative", "employees", type_="check")
    if _check_exists("employees", "ck_employees_federal_claim_amount_nonnegative"):
        op.drop_constraint("ck_employees_federal_claim_amount_nonnegative", "employees", type_="check")
    if _check_exists("employees", "ck_employees_base_rate_cents_nonnegative"):
        op.drop_constraint("ck_employees_base_rate_cents_nonnegative", "employees", type_="check")
    if _check_exists("employees", "ck_employees_default_hours_nonnegative"):
        op.drop_constraint("ck_employees_default_hours_nonnegative", "employees", type_="check")
    if _check_exists("employees", "ck_employees_employment_status_valid"):
        op.drop_constraint("ck_employees_employment_status_valid", "employees", type_="check")

    if _index_exists("employees", "ix_employees_employment_status"):
        op.drop_index("ix_employees_employment_status", table_name="employees")
    if _index_exists("employees", "ix_employees_employee_number"):
        op.drop_index("ix_employees_employee_number", table_name="employees")

    for column in [
        "tax_exemptions",
        "additional_tax_withholding",
        "provincial_claim_amount",
        "federal_claim_amount",
        "province_of_employment",
        "default_hours",
        "payment_method",
        "base_rate_effective_date",
        "base_rate_cents",
        "pay_schedule",
        "employee_number",
        "job_title",
        "department",
        "manager_name",
        "work_location",
        "termination_date",
        "employment_status",
        "mailing_country",
        "mailing_postal_code",
        "mailing_province",
        "mailing_city",
        "mailing_address_line_2",
        "mailing_address_line_1",
        "country",
        "postal_code",
        "province",
        "city",
        "address_line_2",
        "address_line_1",
        "sin",
        "birth_date",
        "legal_last_name",
        "legal_first_name",
    ]:
        if _column_exists("employees", column):
            op.drop_column("employees", column)

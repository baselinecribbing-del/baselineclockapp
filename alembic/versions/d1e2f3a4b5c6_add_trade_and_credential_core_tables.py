"""add trade and credential core tables

Revision ID: d1e2f3a4b5c6
Revises: c3d8a1f5e2b7
Create Date: 2026-03-07 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c3d8a1f5e2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trade_types",
        sa.Column("trade_type_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("trade_type_id"),
        sa.UniqueConstraint("code", name="uq_trade_types_code"),
    )
    op.create_index("ix_trade_types_code", "trade_types", ["code"], unique=False)
    op.create_index("ix_trade_types_is_active", "trade_types", ["is_active"], unique=False)

    op.create_table(
        "credential_types",
        sa.Column("credential_type_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("is_company_level", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("category IN ('SAFETY','TRADE','COMPANY')", name="ck_credential_types_category_valid"),
        sa.PrimaryKeyConstraint("credential_type_id"),
        sa.UniqueConstraint("code", name="uq_credential_types_code"),
    )
    op.create_index("ix_credential_types_code", "credential_types", ["code"], unique=False)
    op.create_index("ix_credential_types_category", "credential_types", ["category"], unique=False)
    op.create_index("ix_credential_types_is_company_level", "credential_types", ["is_company_level"], unique=False)
    op.create_index("ix_credential_types_is_active", "credential_types", ["is_active"], unique=False)

    op.create_table(
        "employee_credentials",
        sa.Column("employee_credential_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("credential_type_id", sa.String(), nullable=False),
        sa.Column("certificate_number", sa.String(), nullable=True),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("document_url", sa.String(), nullable=True),
        sa.Column("verification_status", sa.String(), server_default="PENDING", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "verification_status IN ('PENDING','VERIFIED','EXPIRED')",
            name="ck_employee_credentials_verification_status_valid",
        ),
        sa.ForeignKeyConstraint(["credential_type_id"], ["credential_types.credential_type_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("employee_credential_id"),
    )
    op.create_index("ix_employee_credentials_company_id", "employee_credentials", ["company_id"], unique=False)
    op.create_index("ix_employee_credentials_employee_id", "employee_credentials", ["employee_id"], unique=False)
    op.create_index("ix_employee_credentials_credential_type_id", "employee_credentials", ["credential_type_id"], unique=False)
    op.create_index(
        "ix_employee_credentials_verification_status",
        "employee_credentials",
        ["verification_status"],
        unique=False,
    )
    op.create_index("ix_employee_credentials_expiry_date", "employee_credentials", ["expiry_date"], unique=False)

    op.create_table(
        "job_trade_requirements",
        sa.Column("job_trade_requirement_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("trade_type_id", sa.String(), nullable=False),
        sa.Column("credential_type_id", sa.String(), nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["credential_type_id"], ["credential_types.credential_type_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trade_type_id"], ["trade_types.trade_type_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("job_trade_requirement_id"),
    )
    op.create_index("ix_job_trade_requirements_company_id", "job_trade_requirements", ["company_id"], unique=False)
    op.create_index("ix_job_trade_requirements_job_id", "job_trade_requirements", ["job_id"], unique=False)
    op.create_index("ix_job_trade_requirements_scope_id", "job_trade_requirements", ["scope_id"], unique=False)
    op.create_index("ix_job_trade_requirements_trade_type_id", "job_trade_requirements", ["trade_type_id"], unique=False)
    op.create_index(
        "ix_job_trade_requirements_credential_type_id",
        "job_trade_requirements",
        ["credential_type_id"],
        unique=False,
    )

    trade_types = sa.table(
        "trade_types",
        sa.column("trade_type_id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        trade_types,
        [
            {"trade_type_id": "a6ba5c7f-05b9-4b0b-bf0d-56f4666a0a01", "code": "FOUNDATIONS", "name": "Foundations", "is_active": True},
            {"trade_type_id": "a6ba5c7f-05b9-4b0b-bf0d-56f4666a0a02", "code": "ELECTRICAL", "name": "Electrical", "is_active": True},
            {"trade_type_id": "a6ba5c7f-05b9-4b0b-bf0d-56f4666a0a03", "code": "PLUMBING", "name": "Plumbing", "is_active": True},
            {"trade_type_id": "a6ba5c7f-05b9-4b0b-bf0d-56f4666a0a04", "code": "GAS", "name": "Gas", "is_active": True},
            {"trade_type_id": "a6ba5c7f-05b9-4b0b-bf0d-56f4666a0a05", "code": "EXCAVATION", "name": "Excavation", "is_active": True},
            {"trade_type_id": "a6ba5c7f-05b9-4b0b-bf0d-56f4666a0a06", "code": "FRAMING", "name": "Framing", "is_active": True},
            {"trade_type_id": "a6ba5c7f-05b9-4b0b-bf0d-56f4666a0a07", "code": "ROOFING", "name": "Roofing", "is_active": True},
            {"trade_type_id": "a6ba5c7f-05b9-4b0b-bf0d-56f4666a0a08", "code": "WASTE_HAULING", "name": "Waste Hauling", "is_active": True},
            {"trade_type_id": "a6ba5c7f-05b9-4b0b-bf0d-56f4666a0a09", "code": "GENERAL_CONTRACTING", "name": "General Contracting", "is_active": True},
        ],
    )

    credential_types = sa.table(
        "credential_types",
        sa.column("credential_type_id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("category", sa.String()),
        sa.column("is_company_level", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        credential_types,
        [
            {
                "credential_type_id": "bb7f3477-9a13-4ec0-b2eb-b49f58d8a101",
                "code": "FIRST_AID",
                "name": "First Aid",
                "category": "SAFETY",
                "is_company_level": False,
                "is_active": True,
            },
            {
                "credential_type_id": "bb7f3477-9a13-4ec0-b2eb-b49f58d8a102",
                "code": "FALL_PROTECTION",
                "name": "Fall Protection",
                "category": "SAFETY",
                "is_company_level": False,
                "is_active": True,
            },
            {
                "credential_type_id": "bb7f3477-9a13-4ec0-b2eb-b49f58d8a103",
                "code": "CONFINED_SPACE",
                "name": "Confined Space",
                "category": "SAFETY",
                "is_company_level": False,
                "is_active": True,
            },
            {
                "credential_type_id": "bb7f3477-9a13-4ec0-b2eb-b49f58d8a104",
                "code": "ELECTRICAL_TICKET",
                "name": "Electrical Ticket",
                "category": "TRADE",
                "is_company_level": False,
                "is_active": True,
            },
            {
                "credential_type_id": "bb7f3477-9a13-4ec0-b2eb-b49f58d8a105",
                "code": "GAS_TICKET",
                "name": "Gas Ticket",
                "category": "TRADE",
                "is_company_level": False,
                "is_active": True,
            },
            {
                "credential_type_id": "bb7f3477-9a13-4ec0-b2eb-b49f58d8a106",
                "code": "PLUMBING_LICENSE",
                "name": "Plumbing License",
                "category": "TRADE",
                "is_company_level": False,
                "is_active": True,
            },
            {
                "credential_type_id": "bb7f3477-9a13-4ec0-b2eb-b49f58d8a107",
                "code": "COR",
                "name": "COR",
                "category": "COMPANY",
                "is_company_level": True,
                "is_active": True,
            },
            {
                "credential_type_id": "bb7f3477-9a13-4ec0-b2eb-b49f58d8a108",
                "code": "SECOR",
                "name": "SECOR",
                "category": "COMPANY",
                "is_company_level": True,
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_job_trade_requirements_credential_type_id", table_name="job_trade_requirements")
    op.drop_index("ix_job_trade_requirements_trade_type_id", table_name="job_trade_requirements")
    op.drop_index("ix_job_trade_requirements_scope_id", table_name="job_trade_requirements")
    op.drop_index("ix_job_trade_requirements_job_id", table_name="job_trade_requirements")
    op.drop_index("ix_job_trade_requirements_company_id", table_name="job_trade_requirements")
    op.drop_table("job_trade_requirements")

    op.drop_index("ix_employee_credentials_expiry_date", table_name="employee_credentials")
    op.drop_index("ix_employee_credentials_verification_status", table_name="employee_credentials")
    op.drop_index("ix_employee_credentials_credential_type_id", table_name="employee_credentials")
    op.drop_index("ix_employee_credentials_employee_id", table_name="employee_credentials")
    op.drop_index("ix_employee_credentials_company_id", table_name="employee_credentials")
    op.drop_table("employee_credentials")

    op.drop_index("ix_credential_types_is_active", table_name="credential_types")
    op.drop_index("ix_credential_types_is_company_level", table_name="credential_types")
    op.drop_index("ix_credential_types_category", table_name="credential_types")
    op.drop_index("ix_credential_types_code", table_name="credential_types")
    op.drop_table("credential_types")

    op.drop_index("ix_trade_types_is_active", table_name="trade_types")
    op.drop_index("ix_trade_types_code", table_name="trade_types")
    op.drop_table("trade_types")

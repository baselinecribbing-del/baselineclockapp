"""add deduction_types and deduction_configs tables

Revision ID: d9f1c3a4b5e6
Revises: c8e4f1a2b3d6
Create Date: 2026-03-06 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d9f1c3a4b5e6"
down_revision: Union[str, Sequence[str], None] = "c8e4f1a2b3d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deduction_types",
        sa.Column("deduction_type_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("calculation_method", sa.String(), nullable=False),
        sa.Column("is_statutory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("deduction_type_id"),
    )

    op.create_index("ix_deduction_types_code", "deduction_types", ["code"], unique=False)
    op.create_index("ix_deduction_types_company_id", "deduction_types", ["company_id"], unique=False)

    op.create_table(
        "deduction_configs",
        sa.Column("deduction_config_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("deduction_type_id", sa.String(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("rate_percent", sa.Numeric(7, 4), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("annual_cap_cents", sa.Integer(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "(rate_percent IS NOT NULL AND amount_cents IS NULL) OR "
            "(rate_percent IS NULL AND amount_cents IS NOT NULL)",
            name="ck_deduction_configs_rate_xor_amount",
        ),
        sa.ForeignKeyConstraint(
            ["deduction_type_id"],
            ["deduction_types.deduction_type_id"],
            ondelete="RESTRICT",
            name="fk_deduction_configs_deduction_type_id_deduction_types",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
            name="fk_deduction_configs_employee_id_employees",
        ),
        sa.PrimaryKeyConstraint("deduction_config_id"),
    )

    op.create_index("ix_deduction_configs_company_id", "deduction_configs", ["company_id"], unique=False)
    op.create_index("ix_deduction_configs_employee_id", "deduction_configs", ["employee_id"], unique=False)
    op.create_index("ix_deduction_configs_deduction_type_id", "deduction_configs", ["deduction_type_id"], unique=False)

    op.execute(
        """
        INSERT INTO deduction_types (
            deduction_type_id, company_id, code, name, calculation_method, is_statutory, is_active, created_at
        )
        VALUES
            ('sys-ded-CPP', NULL, 'CPP', 'Canada Pension Plan', 'RATE_PERCENT', true, true, now()),
            ('sys-ded-EI', NULL, 'EI', 'Employment Insurance', 'RATE_PERCENT', true, true, now()),
            ('sys-ded-FEDERAL_TAX', NULL, 'FEDERAL_TAX', 'Federal Income Tax', 'RATE_PERCENT', true, true, now()),
            ('sys-ded-PROVINCIAL_TAX', NULL, 'PROVINCIAL_TAX', 'Provincial Income Tax', 'RATE_PERCENT', true, true, now())
        ;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_deduction_configs_deduction_type_id", table_name="deduction_configs")
    op.drop_index("ix_deduction_configs_employee_id", table_name="deduction_configs")
    op.drop_index("ix_deduction_configs_company_id", table_name="deduction_configs")
    op.drop_table("deduction_configs")

    op.drop_index("ix_deduction_types_company_id", table_name="deduction_types")
    op.drop_index("ix_deduction_types_code", table_name="deduction_types")
    op.drop_table("deduction_types")

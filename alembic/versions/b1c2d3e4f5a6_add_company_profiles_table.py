"""add company profiles table

Revision ID: b1c2d3e4f5a6
Revises: 6a3a389ab2df, a6d9e4c2b1f7
Create Date: 2026-03-11 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = ("6a3a389ab2df", "a6d9e4c2b1f7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_profiles",
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("primary_trade", sa.String(), nullable=False),
        sa.Column("country", sa.String(length=64), nullable=False),
        sa.Column("province_or_state", sa.String(length=64), nullable=False),
        sa.Column("selected_tier", sa.String(), nullable=False),
        sa.Column(
            "enabled_modules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("onboarding_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "selected_tier IN ('tier_1_clock_in','tier_2_clock_in_payroll','tier_3_full_system')",
            name="ck_company_profiles_selected_tier_valid",
        ),
        sa.CheckConstraint("jsonb_typeof(enabled_modules) = 'array'", name="ck_company_profiles_enabled_modules_array"),
        sa.PrimaryKeyConstraint("company_id"),
    )
    op.create_index("ix_company_profiles_selected_tier", "company_profiles", ["selected_tier"], unique=False)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_company_profiles_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_company_profiles_updated_at
        BEFORE UPDATE ON company_profiles
        FOR EACH ROW
        EXECUTE FUNCTION set_company_profiles_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_company_profiles_updated_at ON company_profiles")
    op.execute("DROP FUNCTION IF EXISTS set_company_profiles_updated_at")
    op.drop_index("ix_company_profiles_selected_tier", table_name="company_profiles")
    op.drop_table("company_profiles")

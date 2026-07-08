"""add financial core phase1 ledger foundation

Revision ID: ab4e9c1d2f7a
Revises: b1c2d3e4f5a6, d2e3f4a5b6c7
Create Date: 2026-03-15 10:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "ab4e9c1d2f7a"
down_revision = ("b1c2d3e4f5a6", "d2e3f4a5b6c7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chart_of_accounts",
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("normal_balance", sa.String(length=6), nullable=False),
        sa.Column("parent_account_id", sa.String(), nullable=True),
        sa.Column("allow_posting", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE','CONTRA_ASSET','CONTRA_LIABILITY','CONTRA_REVENUE','CONTRA_EXPENSE')",
            name="ck_chart_of_accounts_account_type_valid",
        ),
        sa.CheckConstraint("normal_balance IN ('DEBIT','CREDIT')", name="ck_chart_of_accounts_normal_balance_valid"),
        sa.CheckConstraint("parent_account_id IS NULL OR parent_account_id <> account_id", name="ck_chart_of_accounts_parent_not_self"),
        sa.ForeignKeyConstraint(["parent_account_id"], ["chart_of_accounts.account_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("account_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_chart_of_accounts_company_code"),
    )
    op.create_index("ix_chart_of_accounts_account_type", "chart_of_accounts", ["account_type"], unique=False)
    op.create_index("ix_chart_of_accounts_code", "chart_of_accounts", ["code"], unique=False)
    op.create_index("ix_chart_of_accounts_company_id", "chart_of_accounts", ["company_id"], unique=False)
    op.create_index("ix_chart_of_accounts_parent_account_id", "chart_of_accounts", ["parent_account_id"], unique=False)

    op.create_table(
        "fiscal_periods",
        sa.Column("fiscal_period_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="OPEN", nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_account_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("period_start <= period_end", name="ck_fiscal_periods_date_order_valid"),
        sa.CheckConstraint("status IN ('OPEN','CLOSED','LOCKED')", name="ck_fiscal_periods_status_valid"),
        sa.ForeignKeyConstraint(["closed_by_user_account_id"], ["user_accounts.user_account_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("fiscal_period_id"),
        sa.UniqueConstraint("company_id", "name", name="uq_fiscal_periods_company_name"),
        sa.UniqueConstraint("company_id", "period_start", "period_end", name="uq_fiscal_periods_company_date_span"),
    )
    op.create_index("ix_fiscal_periods_closed_by_user_account_id", "fiscal_periods", ["closed_by_user_account_id"], unique=False)
    op.create_index("ix_fiscal_periods_company_id", "fiscal_periods", ["company_id"], unique=False)
    op.create_index("ix_fiscal_periods_name", "fiscal_periods", ["name"], unique=False)
    op.create_index("ix_fiscal_periods_period_end", "fiscal_periods", ["period_end"], unique=False)
    op.create_index("ix_fiscal_periods_period_start", "fiscal_periods", ["period_start"], unique=False)
    op.create_index("ix_fiscal_periods_status", "fiscal_periods", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_fiscal_periods_status", table_name="fiscal_periods")
    op.drop_index("ix_fiscal_periods_period_start", table_name="fiscal_periods")
    op.drop_index("ix_fiscal_periods_period_end", table_name="fiscal_periods")
    op.drop_index("ix_fiscal_periods_name", table_name="fiscal_periods")
    op.drop_index("ix_fiscal_periods_company_id", table_name="fiscal_periods")
    op.drop_index("ix_fiscal_periods_closed_by_user_account_id", table_name="fiscal_periods")
    op.drop_table("fiscal_periods")

    op.drop_index("ix_chart_of_accounts_parent_account_id", table_name="chart_of_accounts")
    op.drop_index("ix_chart_of_accounts_company_id", table_name="chart_of_accounts")
    op.drop_index("ix_chart_of_accounts_code", table_name="chart_of_accounts")
    op.drop_index("ix_chart_of_accounts_account_type", table_name="chart_of_accounts")
    op.drop_table("chart_of_accounts")

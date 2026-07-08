"""add financial core journal storage

Revision ID: bc5d1e2f3a4b
Revises: ab4e9c1d2f7a
Create Date: 2026-03-15 11:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "bc5d1e2f3a4b"
down_revision = "ab4e9c1d2f7a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_chart_of_accounts_company_account_id",
        "chart_of_accounts",
        ["company_id", "account_id"],
    )

    op.create_table(
        "journal_entries",
        sa.Column("journal_entry_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_period_id", sa.String(), nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_reference_id", sa.String(length=128), nullable=True),
        sa.Column("reference_number", sa.String(length=64), nullable=True),
        sa.Column("memo", sa.String(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by_user_account_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT','POSTED')", name="ck_journal_entries_status_valid"),
        sa.CheckConstraint(
            "(status = 'POSTED' AND posted_at IS NOT NULL) OR "
            "(status = 'DRAFT' AND posted_at IS NULL)",
            name="ck_journal_entries_posted_state_consistent",
        ),
        sa.ForeignKeyConstraint(["fiscal_period_id"], ["fiscal_periods.fiscal_period_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by_user_account_id"], ["user_accounts.user_account_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("journal_entry_id"),
        sa.UniqueConstraint("company_id", "journal_entry_id", name="uq_journal_entries_company_entry_id"),
    )
    op.create_index("ix_journal_entries_company_id", "journal_entries", ["company_id"], unique=False)
    op.create_index("ix_journal_entries_entry_date", "journal_entries", ["entry_date"], unique=False)
    op.create_index("ix_journal_entries_fiscal_period_id", "journal_entries", ["fiscal_period_id"], unique=False)
    op.create_index("ix_journal_entries_posted_at", "journal_entries", ["posted_at"], unique=False)
    op.create_index(
        "ix_journal_entries_posted_by_user_account_id",
        "journal_entries",
        ["posted_by_user_account_id"],
        unique=False,
    )
    op.create_index("ix_journal_entries_reference_number", "journal_entries", ["reference_number"], unique=False)
    op.create_index("ix_journal_entries_source_reference_id", "journal_entries", ["source_reference_id"], unique=False)
    op.create_index("ix_journal_entries_source_type", "journal_entries", ["source_type"], unique=False)
    op.create_index("ix_journal_entries_status", "journal_entries", ["status"], unique=False)

    op.create_table(
        "journal_entry_lines",
        sa.Column("journal_entry_line_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.String(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("debit_amount_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("credit_amount_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("memo", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "debit_amount_cents >= 0 AND credit_amount_cents >= 0",
            name="ck_journal_entry_lines_nonnegative_amounts",
        ),
        sa.CheckConstraint(
            "(debit_amount_cents > 0 AND credit_amount_cents = 0) OR "
            "(credit_amount_cents > 0 AND debit_amount_cents = 0)",
            name="ck_journal_entry_lines_single_side_nonzero",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "journal_entry_id"],
            ["journal_entries.company_id", "journal_entries.journal_entry_id"],
            name="fk_journal_entry_lines_company_entry",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "account_id"],
            ["chart_of_accounts.company_id", "chart_of_accounts.account_id"],
            name="fk_journal_entry_lines_company_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("journal_entry_line_id"),
        sa.UniqueConstraint(
            "company_id",
            "journal_entry_id",
            "line_number",
            name="uq_journal_entry_lines_company_entry_line_number",
        ),
    )
    op.create_index("ix_journal_entry_lines_account_id", "journal_entry_lines", ["account_id"], unique=False)
    op.create_index("ix_journal_entry_lines_company_id", "journal_entry_lines", ["company_id"], unique=False)
    op.create_index("ix_journal_entry_lines_journal_entry_id", "journal_entry_lines", ["journal_entry_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_journal_entry_lines_journal_entry_id", table_name="journal_entry_lines")
    op.drop_index("ix_journal_entry_lines_company_id", table_name="journal_entry_lines")
    op.drop_index("ix_journal_entry_lines_account_id", table_name="journal_entry_lines")
    op.drop_table("journal_entry_lines")

    op.drop_index("ix_journal_entries_status", table_name="journal_entries")
    op.drop_index("ix_journal_entries_source_type", table_name="journal_entries")
    op.drop_index("ix_journal_entries_source_reference_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_reference_number", table_name="journal_entries")
    op.drop_index("ix_journal_entries_posted_by_user_account_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_posted_at", table_name="journal_entries")
    op.drop_index("ix_journal_entries_fiscal_period_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_entry_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_company_id", table_name="journal_entries")
    op.drop_table("journal_entries")

    op.drop_constraint(
        "uq_chart_of_accounts_company_account_id",
        "chart_of_accounts",
        type_="unique",
    )

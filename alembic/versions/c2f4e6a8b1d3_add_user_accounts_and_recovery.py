"""add user accounts and recovery

Revision ID: c2f4e6a8b1d3
Revises: a7c3d9e4f1b2
Create Date: 2026-03-11 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c2f4e6a8b1d3"
down_revision = "a7c3d9e4f1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("user_account_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lockout_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_account_id"),
        sa.UniqueConstraint("username", name="uq_user_accounts_username"),
        sa.UniqueConstraint("email", name="uq_user_accounts_email"),
    )
    op.create_index("ix_user_accounts_company_id", "user_accounts", ["company_id"], unique=False)
    op.create_index("ix_user_accounts_username", "user_accounts", ["username"], unique=False)
    op.create_index("ix_user_accounts_email", "user_accounts", ["email"], unique=False)

    op.create_table(
        "user_password_history",
        sa.Column("user_password_history_id", sa.String(), nullable=False),
        sa.Column("user_account_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_accounts.user_account_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_password_history_id"),
    )
    op.create_index("ix_user_password_history_company_id", "user_password_history", ["company_id"], unique=False)
    op.create_index("ix_user_password_history_user_account_id", "user_password_history", ["user_account_id"], unique=False)

    op.create_table(
        "user_password_reset_tokens",
        sa.Column("user_password_reset_token_id", sa.String(), nullable=False),
        sa.Column("user_account_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(), server_default="PASSWORD_RESET", nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("purpose IN ('PASSWORD_RESET')", name="ck_user_password_reset_tokens_purpose_valid"),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_accounts.user_account_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_password_reset_token_id"),
        sa.UniqueConstraint("token_hash", name="uq_user_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_user_password_reset_tokens_company_id", "user_password_reset_tokens", ["company_id"], unique=False)
    op.create_index("ix_user_password_reset_tokens_user_account_id", "user_password_reset_tokens", ["user_account_id"], unique=False)
    op.create_index("ix_user_password_reset_tokens_token_hash", "user_password_reset_tokens", ["token_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_password_reset_tokens_token_hash", table_name="user_password_reset_tokens")
    op.drop_index("ix_user_password_reset_tokens_user_account_id", table_name="user_password_reset_tokens")
    op.drop_index("ix_user_password_reset_tokens_company_id", table_name="user_password_reset_tokens")
    op.drop_table("user_password_reset_tokens")
    op.drop_index("ix_user_password_history_user_account_id", table_name="user_password_history")
    op.drop_index("ix_user_password_history_company_id", table_name="user_password_history")
    op.drop_table("user_password_history")
    op.drop_index("ix_user_accounts_email", table_name="user_accounts")
    op.drop_index("ix_user_accounts_username", table_name="user_accounts")
    op.drop_index("ix_user_accounts_company_id", table_name="user_accounts")
    op.drop_table("user_accounts")

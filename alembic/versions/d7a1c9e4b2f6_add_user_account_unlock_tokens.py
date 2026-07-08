"""add user account unlock tokens

Revision ID: d7a1c9e4b2f6
Revises: d4f6a8b2c1e3
Create Date: 2026-03-12 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d7a1c9e4b2f6"
down_revision = "d4f6a8b2c1e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_account_unlock_tokens",
        sa.Column("user_account_unlock_token_id", sa.String(), nullable=False),
        sa.Column("user_account_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(), server_default="ACCOUNT_UNLOCK", nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("purpose IN ('ACCOUNT_UNLOCK')", name="ck_user_account_unlock_tokens_purpose_valid"),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_accounts.user_account_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_account_unlock_token_id"),
        sa.UniqueConstraint("token_hash", name="uq_user_account_unlock_tokens_token_hash"),
    )
    op.create_index("ix_user_account_unlock_tokens_company_id", "user_account_unlock_tokens", ["company_id"], unique=False)
    op.create_index(
        "ix_user_account_unlock_tokens_user_account_id",
        "user_account_unlock_tokens",
        ["user_account_id"],
        unique=False,
    )
    op.create_index("ix_user_account_unlock_tokens_token_hash", "user_account_unlock_tokens", ["token_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_account_unlock_tokens_token_hash", table_name="user_account_unlock_tokens")
    op.drop_index("ix_user_account_unlock_tokens_user_account_id", table_name="user_account_unlock_tokens")
    op.drop_index("ix_user_account_unlock_tokens_company_id", table_name="user_account_unlock_tokens")
    op.drop_table("user_account_unlock_tokens")

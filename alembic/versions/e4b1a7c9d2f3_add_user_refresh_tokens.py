"""add user refresh tokens

Revision ID: e4b1a7c9d2f3
Revises: d7a1c9e4b2f6
Create Date: 2026-03-12 13:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e4b1a7c9d2f3"
down_revision = "d7a1c9e4b2f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_refresh_tokens",
        sa.Column("user_refresh_token_id", sa.String(), nullable=False),
        sa.Column("user_account_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_accounts.user_account_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_refresh_token_id"),
        sa.UniqueConstraint("token_hash", name="uq_user_refresh_tokens_token_hash"),
    )
    op.create_index("ix_user_refresh_tokens_company_id", "user_refresh_tokens", ["company_id"], unique=False)
    op.create_index("ix_user_refresh_tokens_expires_at", "user_refresh_tokens", ["expires_at"], unique=False)
    op.create_index("ix_user_refresh_tokens_revoked_at", "user_refresh_tokens", ["revoked_at"], unique=False)
    op.create_index("ix_user_refresh_tokens_token_hash", "user_refresh_tokens", ["token_hash"], unique=False)
    op.create_index("ix_user_refresh_tokens_user_account_id", "user_refresh_tokens", ["user_account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_refresh_tokens_user_account_id", table_name="user_refresh_tokens")
    op.drop_index("ix_user_refresh_tokens_token_hash", table_name="user_refresh_tokens")
    op.drop_index("ix_user_refresh_tokens_revoked_at", table_name="user_refresh_tokens")
    op.drop_index("ix_user_refresh_tokens_expires_at", table_name="user_refresh_tokens")
    op.drop_index("ix_user_refresh_tokens_company_id", table_name="user_refresh_tokens")
    op.drop_table("user_refresh_tokens")

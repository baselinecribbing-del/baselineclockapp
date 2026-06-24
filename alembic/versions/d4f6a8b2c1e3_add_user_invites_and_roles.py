"""add user invites and roles

Revision ID: d4f6a8b2c1e3
Revises: c2f4e6a8b1d3
Create Date: 2026-03-11 13:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d4f6a8b2c1e3"
down_revision = "c2f4e6a8b1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_accounts", sa.Column("role", sa.String(length=32), server_default="MEMBER", nullable=False))

    op.create_table(
        "user_invite_tokens",
        sa.Column("user_invite_token_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="MEMBER", nullable=False),
        sa.Column("invited_by_user_account_id", sa.String(), nullable=True),
        sa.Column("purpose", sa.String(), server_default="ACCOUNT_INVITE", nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("purpose IN ('ACCOUNT_INVITE')", name="ck_user_invite_tokens_purpose_valid"),
        sa.ForeignKeyConstraint(["invited_by_user_account_id"], ["user_accounts.user_account_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_invite_token_id"),
        sa.UniqueConstraint("token_hash", name="uq_user_invite_tokens_token_hash"),
    )
    op.create_index("ix_user_invite_tokens_company_id", "user_invite_tokens", ["company_id"], unique=False)
    op.create_index("ix_user_invite_tokens_email", "user_invite_tokens", ["email"], unique=False)
    op.create_index(
        "ix_user_invite_tokens_invited_by_user_account_id",
        "user_invite_tokens",
        ["invited_by_user_account_id"],
        unique=False,
    )
    op.create_index("ix_user_invite_tokens_token_hash", "user_invite_tokens", ["token_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_invite_tokens_token_hash", table_name="user_invite_tokens")
    op.drop_index("ix_user_invite_tokens_invited_by_user_account_id", table_name="user_invite_tokens")
    op.drop_index("ix_user_invite_tokens_email", table_name="user_invite_tokens")
    op.drop_index("ix_user_invite_tokens_company_id", table_name="user_invite_tokens")
    op.drop_table("user_invite_tokens")
    op.drop_column("user_accounts", "role")

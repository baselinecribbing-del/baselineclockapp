"""add user mfa support

Revision ID: f1c2d3e4a5b6
Revises: e4b1a7c9d2f3
Create Date: 2026-03-12 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f1c2d3e4a5b6"
down_revision = "e4b1a7c9d2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_accounts", sa.Column("mfa_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("user_accounts", sa.Column("mfa_totp_secret_encrypted", sa.String(), nullable=True))
    op.add_column("user_accounts", sa.Column("mfa_setup_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_accounts", sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("user_refresh_tokens", sa.Column("mfa_authenticated", sa.Boolean(), server_default="false", nullable=False))

    op.create_table(
        "user_mfa_recovery_codes",
        sa.Column("user_mfa_recovery_code_id", sa.String(), nullable=False),
        sa.Column("user_account_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_accounts.user_account_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_mfa_recovery_code_id"),
        sa.UniqueConstraint("code_hash", name="uq_user_mfa_recovery_codes_code_hash"),
    )
    op.create_index("ix_user_mfa_recovery_codes_code_hash", "user_mfa_recovery_codes", ["code_hash"], unique=False)
    op.create_index("ix_user_mfa_recovery_codes_company_id", "user_mfa_recovery_codes", ["company_id"], unique=False)
    op.create_index("ix_user_mfa_recovery_codes_user_account_id", "user_mfa_recovery_codes", ["user_account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_mfa_recovery_codes_user_account_id", table_name="user_mfa_recovery_codes")
    op.drop_index("ix_user_mfa_recovery_codes_company_id", table_name="user_mfa_recovery_codes")
    op.drop_index("ix_user_mfa_recovery_codes_code_hash", table_name="user_mfa_recovery_codes")
    op.drop_table("user_mfa_recovery_codes")

    op.drop_column("user_refresh_tokens", "mfa_authenticated")

    op.drop_column("user_accounts", "mfa_enabled_at")
    op.drop_column("user_accounts", "mfa_setup_started_at")
    op.drop_column("user_accounts", "mfa_totp_secret_encrypted")
    op.drop_column("user_accounts", "mfa_enabled")

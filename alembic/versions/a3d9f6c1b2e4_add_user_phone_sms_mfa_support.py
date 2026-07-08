"""add user phone sms mfa support

Revision ID: a3d9f6c1b2e4
Revises: f1c2d3e4a5b6
Create Date: 2026-03-12 20:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a3d9f6c1b2e4"
down_revision = "f1c2d3e4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_accounts", sa.Column("phone_number", sa.String(length=32), nullable=True))
    op.add_column("user_accounts", sa.Column("phone_verified", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("user_accounts", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_accounts", sa.Column("preferred_mfa_method", sa.String(length=16), server_default="totp", nullable=False))
    op.add_column("user_accounts", sa.Column("sms_mfa_enabled", sa.Boolean(), server_default="false", nullable=False))

    op.create_table(
        "user_sms_codes",
        sa.Column("user_sms_code_id", sa.String(), nullable=False),
        sa.Column("user_account_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("code_encrypted", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("purpose IN ('PHONE_VERIFICATION', 'MFA_LOGIN')", name="ck_user_sms_codes_purpose_valid"),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_accounts.user_account_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_sms_code_id"),
        sa.UniqueConstraint("code_hash", name="uq_user_sms_codes_code_hash"),
    )
    op.create_index("ix_user_sms_codes_code_hash", "user_sms_codes", ["code_hash"], unique=False)
    op.create_index("ix_user_sms_codes_company_id", "user_sms_codes", ["company_id"], unique=False)
    op.create_index("ix_user_sms_codes_user_account_id", "user_sms_codes", ["user_account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_sms_codes_user_account_id", table_name="user_sms_codes")
    op.drop_index("ix_user_sms_codes_company_id", table_name="user_sms_codes")
    op.drop_index("ix_user_sms_codes_code_hash", table_name="user_sms_codes")
    op.drop_table("user_sms_codes")

    op.drop_column("user_accounts", "sms_mfa_enabled")
    op.drop_column("user_accounts", "preferred_mfa_method")
    op.drop_column("user_accounts", "phone_verified_at")
    op.drop_column("user_accounts", "phone_verified")
    op.drop_column("user_accounts", "phone_number")

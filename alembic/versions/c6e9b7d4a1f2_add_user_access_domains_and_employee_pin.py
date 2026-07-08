"""add user access domains and employee pin

Revision ID: c6e9b7d4a1f2
Revises: a3d9f6c1b2e4
Create Date: 2026-03-12 11:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c6e9b7d4a1f2"
down_revision = "a3d9f6c1b2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("can_access_operations", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "user_accounts",
        sa.Column("can_access_employee_self_service", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("user_accounts", sa.Column("linked_employee_id", sa.Integer(), nullable=True))
    op.add_column(
        "user_accounts",
        sa.Column("granted_permissions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column("user_accounts", sa.Column("employee_pin_hash", sa.String(), nullable=True))
    op.add_column(
        "user_accounts",
        sa.Column("employee_pin_failed_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("user_accounts", sa.Column("employee_pin_lockout_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_accounts", sa.Column("employee_pin_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_user_accounts_linked_employee_id"), "user_accounts", ["linked_employee_id"], unique=False)

    op.execute(
        """
        UPDATE user_accounts
        SET can_access_operations = CASE WHEN UPPER(role) = 'EMPLOYEE' THEN false ELSE true END,
            can_access_employee_self_service = CASE WHEN UPPER(role) = 'EMPLOYEE' THEN true ELSE false END
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_accounts_linked_employee_id"), table_name="user_accounts")
    op.drop_column("user_accounts", "employee_pin_changed_at")
    op.drop_column("user_accounts", "employee_pin_lockout_until")
    op.drop_column("user_accounts", "employee_pin_failed_attempt_count")
    op.drop_column("user_accounts", "employee_pin_hash")
    op.drop_column("user_accounts", "granted_permissions")
    op.drop_column("user_accounts", "linked_employee_id")
    op.drop_column("user_accounts", "can_access_employee_self_service")
    op.drop_column("user_accounts", "can_access_operations")

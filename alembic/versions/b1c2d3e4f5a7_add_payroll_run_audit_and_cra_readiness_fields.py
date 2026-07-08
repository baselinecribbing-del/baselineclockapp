"""add payroll run audit and CRA readiness fields

Revision ID: b1c2d3e4f5a7
Revises: f8c1d2e3a4b5
Create Date: 2026-03-13 18:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a7"
down_revision: Union[str, Sequence[str], None] = "f8c1d2e3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_run", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("payroll_run", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_run", sa.Column("finalized_by_user_id", sa.String(), nullable=True))
    op.add_column("payroll_run", sa.Column("finalize_consistency_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.execute("UPDATE payroll_run SET updated_at = COALESCE(created_at, now())")

    op.add_column("company_profiles", sa.Column("cra_business_number", sa.String(length=32), nullable=True))
    op.add_column("company_profiles", sa.Column("cra_payroll_program_account_number", sa.String(length=32), nullable=True))
    op.add_column("company_profiles", sa.Column("payroll_registration_country", sa.String(length=64), nullable=True))

    op.create_table(
        "payroll_run_audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("payroll_run_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["payroll_run_id"],
            ["payroll_run.payroll_run_id"],
            name="fk_payroll_run_audit_events_payroll_run_id_payroll_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payroll_run_audit_events_company_id", "payroll_run_audit_events", ["company_id"], unique=False)
    op.create_index("ix_payroll_run_audit_events_payroll_run_id", "payroll_run_audit_events", ["payroll_run_id"], unique=False)
    op.create_index("ix_payroll_run_audit_events_event_type", "payroll_run_audit_events", ["event_type"], unique=False)
    op.create_index(
        "ix_payroll_run_audit_events_company_run_time",
        "payroll_run_audit_events",
        ["company_id", "payroll_run_id", "event_timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_run_audit_events_company_run_time", table_name="payroll_run_audit_events")
    op.drop_index("ix_payroll_run_audit_events_event_type", table_name="payroll_run_audit_events")
    op.drop_index("ix_payroll_run_audit_events_payroll_run_id", table_name="payroll_run_audit_events")
    op.drop_index("ix_payroll_run_audit_events_company_id", table_name="payroll_run_audit_events")
    op.drop_table("payroll_run_audit_events")

    op.drop_column("company_profiles", "payroll_registration_country")
    op.drop_column("company_profiles", "cra_payroll_program_account_number")
    op.drop_column("company_profiles", "cra_business_number")

    op.drop_column("payroll_run", "finalize_consistency_snapshot")
    op.drop_column("payroll_run", "finalized_by_user_id")
    op.drop_column("payroll_run", "finalized_at")
    op.drop_column("payroll_run", "updated_at")

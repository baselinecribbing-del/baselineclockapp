"""add journal posting audit events

Revision ID: e2f3a4b5c6d7
Revises: de8f2a1b3c4d
Create Date: 2026-03-15 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e2f3a4b5c6d7"
down_revision = "de8f2a1b3c4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_posting_audit_events",
        sa.Column("journal_posting_audit_event_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("actor_user_account_id", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("source_reference_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('POST_ATTEMPT')",
            name="ck_journal_posting_audit_events_event_type_valid",
        ),
        sa.CheckConstraint(
            "result IN ('SUCCESS','FAILED')",
            name="ck_journal_posting_audit_events_result_valid",
        ),
        sa.PrimaryKeyConstraint("journal_posting_audit_event_id"),
    )
    op.create_index(
        "ix_journal_posting_audit_events_actor_user_account_id",
        "journal_posting_audit_events",
        ["actor_user_account_id"],
        unique=False,
    )
    op.create_index("ix_journal_posting_audit_events_company_id", "journal_posting_audit_events", ["company_id"], unique=False)
    op.create_index("ix_journal_posting_audit_events_created_at", "journal_posting_audit_events", ["created_at"], unique=False)
    op.create_index("ix_journal_posting_audit_events_error_code", "journal_posting_audit_events", ["error_code"], unique=False)
    op.create_index("ix_journal_posting_audit_events_event_type", "journal_posting_audit_events", ["event_type"], unique=False)
    op.create_index(
        "ix_journal_posting_audit_events_journal_entry_id",
        "journal_posting_audit_events",
        ["journal_entry_id"],
        unique=False,
    )
    op.create_index("ix_journal_posting_audit_events_result", "journal_posting_audit_events", ["result"], unique=False)
    op.create_index("ix_journal_posting_audit_events_source_reference_id", "journal_posting_audit_events", ["source_reference_id"], unique=False)
    op.create_index("ix_journal_posting_audit_events_source_type", "journal_posting_audit_events", ["source_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_journal_posting_audit_events_source_type", table_name="journal_posting_audit_events")
    op.drop_index("ix_journal_posting_audit_events_source_reference_id", table_name="journal_posting_audit_events")
    op.drop_index("ix_journal_posting_audit_events_result", table_name="journal_posting_audit_events")
    op.drop_index("ix_journal_posting_audit_events_journal_entry_id", table_name="journal_posting_audit_events")
    op.drop_index("ix_journal_posting_audit_events_event_type", table_name="journal_posting_audit_events")
    op.drop_index("ix_journal_posting_audit_events_error_code", table_name="journal_posting_audit_events")
    op.drop_index("ix_journal_posting_audit_events_created_at", table_name="journal_posting_audit_events")
    op.drop_index("ix_journal_posting_audit_events_company_id", table_name="journal_posting_audit_events")
    op.drop_index("ix_journal_posting_audit_events_actor_user_account_id", table_name="journal_posting_audit_events")
    op.drop_table("journal_posting_audit_events")

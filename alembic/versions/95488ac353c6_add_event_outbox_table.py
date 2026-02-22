"""add event_outbox table

Revision ID: 95488ac353c6
Revises: 7fbf9a61e31a
Create Date: 2026-02-22 10:43:37.127507
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "95488ac353c6"
down_revision: Union[str, Sequence[str], None] = "7fbf9a61e31a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("company_id", "event_type", "idempotency_key", name="uq_event_outbox_idempotency"),
    )

    op.create_index("ix_event_outbox_company_event", "event_outbox", ["company_id", "event_type"], unique=False)
    op.create_index("ix_event_outbox_processed", "event_outbox", ["processed", "created_at"], unique=False)
    op.create_index(op.f("ix_event_outbox_company_id"), "event_outbox", ["company_id"], unique=False)
    op.create_index(op.f("ix_event_outbox_event_type"), "event_outbox", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_event_outbox_event_type"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_company_id"), table_name="event_outbox")
    op.drop_index("ix_event_outbox_processed", table_name="event_outbox")
    op.drop_index("ix_event_outbox_company_event", table_name="event_outbox")
    op.drop_table("event_outbox")

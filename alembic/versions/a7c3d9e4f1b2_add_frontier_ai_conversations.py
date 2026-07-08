"""add frontier ai conversations

Revision ID: a7c3d9e4f1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-03-11 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a7c3d9e4f1b2"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "frontier_ai_conversations",
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        "ix_frontier_ai_conversations_company_id",
        "frontier_ai_conversations",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_frontier_ai_conversations_user_id",
        "frontier_ai_conversations",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "frontier_ai_messages",
        sa.Column("frontier_ai_message_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("surface_context", sa.String(), nullable=True),
        sa.Column("page_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("selected_record", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('USER','ASSISTANT')", name="ck_frontier_ai_messages_role_valid"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["frontier_ai_conversations.conversation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("frontier_ai_message_id"),
    )
    op.create_index("ix_frontier_ai_messages_company_id", "frontier_ai_messages", ["company_id"], unique=False)
    op.create_index(
        "ix_frontier_ai_messages_conversation_id",
        "frontier_ai_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_index("ix_frontier_ai_messages_role", "frontier_ai_messages", ["role"], unique=False)
    op.create_index("ix_frontier_ai_messages_user_id", "frontier_ai_messages", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_frontier_ai_messages_user_id", table_name="frontier_ai_messages")
    op.drop_index("ix_frontier_ai_messages_role", table_name="frontier_ai_messages")
    op.drop_index("ix_frontier_ai_messages_conversation_id", table_name="frontier_ai_messages")
    op.drop_index("ix_frontier_ai_messages_company_id", table_name="frontier_ai_messages")
    op.drop_table("frontier_ai_messages")
    op.drop_index("ix_frontier_ai_conversations_user_id", table_name="frontier_ai_conversations")
    op.drop_index("ix_frontier_ai_conversations_company_id", table_name="frontier_ai_conversations")
    op.drop_table("frontier_ai_conversations")

"""add paystub delivery state fields

Revision ID: a7c3d9e2f1b4
Revises: f2b7c9d1e4a6
Create Date: 2026-03-06 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c3d9e2f1b4"
down_revision: Union[str, Sequence[str], None] = "f2b7c9d1e4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "paystubs",
        sa.Column("delivery_status", sa.String(), nullable=False, server_default="PENDING"),
    )
    op.add_column("paystubs", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("paystubs", sa.Column("sent_by_user_id", sa.String(), nullable=True))

    op.create_index("ix_paystubs_delivery_status", "paystubs", ["delivery_status"], unique=False)

    op.create_check_constraint(
        "ck_paystubs_delivery_status_valid",
        "paystubs",
        "delivery_status in ('PENDING','SENT')",
    )
    op.create_check_constraint(
        "ck_paystubs_delivery_state_consistent",
        "paystubs",
        "(delivery_status = 'PENDING' AND sent_at IS NULL AND sent_by_user_id IS NULL) OR "
        "(delivery_status = 'SENT' AND sent_at IS NOT NULL AND sent_by_user_id IS NOT NULL)",
    )

    op.alter_column("paystubs", "delivery_status", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_paystubs_delivery_state_consistent", "paystubs", type_="check")
    op.drop_constraint("ck_paystubs_delivery_status_valid", "paystubs", type_="check")
    op.drop_index("ix_paystubs_delivery_status", table_name="paystubs")
    op.drop_column("paystubs", "sent_by_user_id")
    op.drop_column("paystubs", "sent_at")
    op.drop_column("paystubs", "delivery_status")

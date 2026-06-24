"""add bin service photos and ticket completion fields

Revision ID: e3b7a1c9d4f2
Revises: d2a6c4e7b9f1
Create Date: 2026-03-07 10:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e3b7a1c9d4f2"
down_revision: Union[str, Sequence[str], None] = "d2a6c4e7b9f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bin_service_tickets", sa.Column("completed_by_user_id", sa.String(), nullable=True))

    op.create_table(
        "bin_service_photos",
        sa.Column("bin_service_photo_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("bin_service_ticket_id", sa.String(), nullable=False),
        sa.Column("photo_type", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("captured_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "photo_type IN ('DROP_PROOF','SWAP_PROOF','PICKUP_PROOF','RECEIPT')",
            name="ck_bin_service_photos_photo_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["bin_service_ticket_id"],
            ["bin_service_tickets.bin_service_ticket_id"],
            ondelete="RESTRICT",
            name="fk_bin_service_photos_ticket",
        ),
        sa.PrimaryKeyConstraint("bin_service_photo_id"),
    )
    op.create_index("ix_bin_service_photos_company_id", "bin_service_photos", ["company_id"], unique=False)
    op.create_index(
        "ix_bin_service_photos_bin_service_ticket_id",
        "bin_service_photos",
        ["bin_service_ticket_id"],
        unique=False,
    )
    op.create_index("ix_bin_service_photos_photo_type", "bin_service_photos", ["photo_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bin_service_photos_photo_type", table_name="bin_service_photos")
    op.drop_index("ix_bin_service_photos_bin_service_ticket_id", table_name="bin_service_photos")
    op.drop_index("ix_bin_service_photos_company_id", table_name="bin_service_photos")
    op.drop_table("bin_service_photos")

    op.drop_column("bin_service_tickets", "completed_by_user_id")

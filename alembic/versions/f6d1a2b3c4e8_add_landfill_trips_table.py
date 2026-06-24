"""add landfill trips table

Revision ID: f6d1a2b3c4e8
Revises: e3b7a1c9d4f2
Create Date: 2026-03-07 11:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6d1a2b3c4e8"
down_revision: Union[str, Sequence[str], None] = "e3b7a1c9d4f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "landfill_trips",
        sa.Column("landfill_trip_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("bin_service_ticket_id", sa.String(), nullable=False),
        sa.Column("bin_asset_id", sa.String(), nullable=False),
        sa.Column("dump_site_name", sa.String(), nullable=False),
        sa.Column("receipt_photo_id", sa.String(), nullable=True),
        sa.Column("dump_cost_cents", sa.Integer(), nullable=False),
        sa.Column("km_driven", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bin_service_ticket_id"],
            ["bin_service_tickets.bin_service_ticket_id"],
            ondelete="RESTRICT",
            name="fk_landfill_trips_ticket",
        ),
        sa.ForeignKeyConstraint(
            ["bin_asset_id"],
            ["bin_assets.bin_asset_id"],
            ondelete="RESTRICT",
            name="fk_landfill_trips_asset",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_photo_id"],
            ["bin_service_photos.bin_service_photo_id"],
            ondelete="RESTRICT",
            name="fk_landfill_trips_receipt_photo",
        ),
        sa.PrimaryKeyConstraint("landfill_trip_id"),
        sa.UniqueConstraint("company_id", "bin_service_ticket_id", name="uq_landfill_trips_company_ticket"),
    )
    op.create_index("ix_landfill_trips_company_id", "landfill_trips", ["company_id"], unique=False)
    op.create_index(
        "ix_landfill_trips_bin_service_ticket_id",
        "landfill_trips",
        ["bin_service_ticket_id"],
        unique=False,
    )
    op.create_index("ix_landfill_trips_bin_asset_id", "landfill_trips", ["bin_asset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_landfill_trips_bin_asset_id", table_name="landfill_trips")
    op.drop_index("ix_landfill_trips_bin_service_ticket_id", table_name="landfill_trips")
    op.drop_index("ix_landfill_trips_company_id", table_name="landfill_trips")
    op.drop_table("landfill_trips")

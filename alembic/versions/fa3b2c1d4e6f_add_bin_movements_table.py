"""add bin movements table

Revision ID: fa3b2c1d4e6f
Revises: f4c2b8a1d9e7
Create Date: 2026-03-07 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fa3b2c1d4e6f"
down_revision: Union[str, Sequence[str], None] = "f4c2b8a1d9e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bin_movements",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("bin_id", sa.String(), nullable=False),
        sa.Column("movement_type", sa.String(), nullable=False),
        sa.Column("from_location_type", sa.String(), nullable=False),
        sa.Column("from_location_id", sa.String(), nullable=True),
        sa.Column("to_location_type", sa.String(), nullable=False),
        sa.Column("to_location_id", sa.String(), nullable=True),
        sa.Column("related_ticket_id", sa.String(), nullable=True),
        sa.Column("related_landfill_trip_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "movement_type IN ('DROP','SWAP_OUT','SWAP_IN','LANDFILL_DUMP','RETURN_TO_YARD')",
            name="ck_bin_movements_movement_type_valid",
        ),
        sa.CheckConstraint(
            "from_location_type IN ('SITE','LANDFILL','YARD')",
            name="ck_bin_movements_from_location_type_valid",
        ),
        sa.CheckConstraint(
            "to_location_type IN ('SITE','LANDFILL','YARD')",
            name="ck_bin_movements_to_location_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["bin_id"],
            ["bin_assets.bin_asset_id"],
            ondelete="RESTRICT",
            name="fk_bin_movements_bin_asset",
        ),
        sa.ForeignKeyConstraint(
            ["related_ticket_id"],
            ["bin_service_tickets.bin_service_ticket_id"],
            ondelete="RESTRICT",
            name="fk_bin_movements_ticket",
        ),
        sa.ForeignKeyConstraint(
            ["related_landfill_trip_id"],
            ["landfill_trips.landfill_trip_id"],
            ondelete="RESTRICT",
            name="fk_bin_movements_landfill_trip",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bin_movements_company_id", "bin_movements", ["company_id"], unique=False)
    op.create_index("ix_bin_movements_bin_id", "bin_movements", ["bin_id"], unique=False)
    op.create_index("ix_bin_movements_movement_type", "bin_movements", ["movement_type"], unique=False)
    op.create_index("ix_bin_movements_related_ticket_id", "bin_movements", ["related_ticket_id"], unique=False)
    op.create_index(
        "ix_bin_movements_related_landfill_trip_id",
        "bin_movements",
        ["related_landfill_trip_id"],
        unique=False,
    )
    op.create_index("ix_bin_movements_created_at", "bin_movements", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bin_movements_created_at", table_name="bin_movements")
    op.drop_index("ix_bin_movements_related_landfill_trip_id", table_name="bin_movements")
    op.drop_index("ix_bin_movements_related_ticket_id", table_name="bin_movements")
    op.drop_index("ix_bin_movements_movement_type", table_name="bin_movements")
    op.drop_index("ix_bin_movements_bin_id", table_name="bin_movements")
    op.drop_index("ix_bin_movements_company_id", table_name="bin_movements")
    op.drop_table("bin_movements")

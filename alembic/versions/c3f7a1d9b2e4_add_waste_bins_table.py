"""add waste bins table

Revision ID: c3f7a1d9b2e4
Revises: b7e2c4d9a1f3
Create Date: 2026-03-07 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3f7a1d9b2e4"
down_revision: Union[str, Sequence[str], None] = "b7e2c4d9a1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "waste_bins",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("bin_number", sa.String(), nullable=False),
        sa.Column("capacity_yards", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="AVAILABLE"),
        sa.Column("current_site_id", sa.String(), nullable=True),
        sa.Column("current_ticket_id", sa.String(), nullable=True),
        sa.Column("last_service_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','ON_SITE','IN_TRANSIT','AT_LANDFILL','OUT_OF_SERVICE')",
            name="ck_waste_bins_status_valid",
        ),
        sa.ForeignKeyConstraint(["current_site_id"], ["customer_sites.customer_site_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_ticket_id"], ["bin_service_tickets.bin_service_ticket_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "bin_number", name="uq_waste_bins_company_bin_number"),
    )
    op.create_index("ix_waste_bins_company_id", "waste_bins", ["company_id"], unique=False)
    op.create_index("ix_waste_bins_status", "waste_bins", ["status"], unique=False)
    op.create_index("ix_waste_bins_current_site_id", "waste_bins", ["current_site_id"], unique=False)
    op.create_index("ix_waste_bins_current_ticket_id", "waste_bins", ["current_ticket_id"], unique=False)

    op.drop_constraint("ck_bin_service_tickets_service_type_valid", "bin_service_tickets", type_="check")
    op.create_check_constraint(
        "ck_bin_service_tickets_service_type_valid",
        "bin_service_tickets",
        "service_type IN ('DROP','SWAP','PICKUP','DROP_BIN','SWAP_BIN','PICKUP_BIN','LANDFILL_DUMP')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_bin_service_tickets_service_type_valid", "bin_service_tickets", type_="check")
    op.create_check_constraint(
        "ck_bin_service_tickets_service_type_valid",
        "bin_service_tickets",
        "service_type IN ('DROP','SWAP','PICKUP')",
    )

    op.drop_index("ix_waste_bins_current_ticket_id", table_name="waste_bins")
    op.drop_index("ix_waste_bins_current_site_id", table_name="waste_bins")
    op.drop_index("ix_waste_bins_status", table_name="waste_bins")
    op.drop_index("ix_waste_bins_company_id", table_name="waste_bins")
    op.drop_table("waste_bins")

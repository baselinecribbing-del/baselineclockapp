"""add job geofence and clock-in location

Revision ID: e1943f73e695
Revises: c734b3e93018
Create Date: 2026-03-02 15:14:29.521795

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1943f73e695"
down_revision: Union[str, Sequence[str], None] = "c734b3e93018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- jobs: site geofence ----
    op.add_column("jobs", sa.Column("site_lat", sa.Numeric(9, 6), nullable=True))
    op.add_column("jobs", sa.Column("site_lng", sa.Numeric(9, 6), nullable=True))
    op.add_column("jobs", sa.Column("site_radius_m", sa.Integer(), nullable=True))

    # ---- time_entries: clock-in location capture ----
    op.add_column("time_entries", sa.Column("clock_in_lat", sa.Numeric(9, 6), nullable=True))
    op.add_column("time_entries", sa.Column("clock_in_lng", sa.Numeric(9, 6), nullable=True))
    op.add_column("time_entries", sa.Column("clock_in_accuracy_m", sa.Integer(), nullable=True))
    op.add_column("time_entries", sa.Column("clock_in_distance_m", sa.Integer(), nullable=True))
    op.add_column("time_entries", sa.Column("clock_in_address", sa.Text(), nullable=True))
    op.add_column("time_entries", sa.Column("clock_in_address_source", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("time_entries", "clock_in_address_source")
    op.drop_column("time_entries", "clock_in_address")
    op.drop_column("time_entries", "clock_in_distance_m")
    op.drop_column("time_entries", "clock_in_accuracy_m")
    op.drop_column("time_entries", "clock_in_lng")
    op.drop_column("time_entries", "clock_in_lat")

    op.drop_column("jobs", "site_radius_m")
    op.drop_column("jobs", "site_lng")
    op.drop_column("jobs", "site_lat")

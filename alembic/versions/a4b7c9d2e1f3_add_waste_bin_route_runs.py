"""add waste bin route runs

Revision ID: a4b7c9d2e1f3
Revises: 9f2c6d7b8a1e
Create Date: 2026-03-10 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4b7c9d2e1f3"
down_revision: Union[str, Sequence[str], None] = "9f2c6d7b8a1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bin_route_runs",
        sa.Column("route_run_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("route_label", sa.String(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), server_default="PLANNED", nullable=False),
        sa.Column("assigned_employee_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('PLANNED','ACTIVE','COMPLETED','CANCELLED')",
            name="ck_bin_route_runs_status_valid",
        ),
        sa.ForeignKeyConstraint(["assigned_employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("route_run_id"),
    )
    op.create_index("ix_bin_route_runs_company_id", "bin_route_runs", ["company_id"], unique=False)
    op.create_index("ix_bin_route_runs_route_label", "bin_route_runs", ["route_label"], unique=False)
    op.create_index("ix_bin_route_runs_scheduled_date", "bin_route_runs", ["scheduled_date"], unique=False)
    op.create_index("ix_bin_route_runs_status", "bin_route_runs", ["status"], unique=False)
    op.create_index("ix_bin_route_runs_assigned_employee_id", "bin_route_runs", ["assigned_employee_id"], unique=False)
    op.create_index("ix_bin_route_runs_created_at", "bin_route_runs", ["created_at"], unique=False)

    op.create_table(
        "bin_route_run_stops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("route_run_id", sa.String(), nullable=False),
        sa.Column("bin_service_ticket_id", sa.String(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=True),
        sa.Column("bin_asset_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["bin_asset_id"], ["bin_assets.bin_asset_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bin_service_ticket_id"], ["bin_service_tickets.bin_service_ticket_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_run_id"], ["bin_route_runs.route_run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "route_run_id", "bin_service_ticket_id", name="uq_bin_route_run_stops_route_ticket"),
    )
    op.create_index("ix_bin_route_run_stops_company_id", "bin_route_run_stops", ["company_id"], unique=False)
    op.create_index("ix_bin_route_run_stops_route_run_id", "bin_route_run_stops", ["route_run_id"], unique=False)
    op.create_index("ix_bin_route_run_stops_bin_service_ticket_id", "bin_route_run_stops", ["bin_service_ticket_id"], unique=False)
    op.create_index("ix_bin_route_run_stops_sequence_index", "bin_route_run_stops", ["sequence_index"], unique=False)
    op.create_index("ix_bin_route_run_stops_bin_asset_id", "bin_route_run_stops", ["bin_asset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bin_route_run_stops_bin_asset_id", table_name="bin_route_run_stops")
    op.drop_index("ix_bin_route_run_stops_sequence_index", table_name="bin_route_run_stops")
    op.drop_index("ix_bin_route_run_stops_bin_service_ticket_id", table_name="bin_route_run_stops")
    op.drop_index("ix_bin_route_run_stops_route_run_id", table_name="bin_route_run_stops")
    op.drop_index("ix_bin_route_run_stops_company_id", table_name="bin_route_run_stops")
    op.drop_table("bin_route_run_stops")

    op.drop_index("ix_bin_route_runs_created_at", table_name="bin_route_runs")
    op.drop_index("ix_bin_route_runs_assigned_employee_id", table_name="bin_route_runs")
    op.drop_index("ix_bin_route_runs_status", table_name="bin_route_runs")
    op.drop_index("ix_bin_route_runs_scheduled_date", table_name="bin_route_runs")
    op.drop_index("ix_bin_route_runs_route_label", table_name="bin_route_runs")
    op.drop_index("ix_bin_route_runs_company_id", table_name="bin_route_runs")
    op.drop_table("bin_route_runs")

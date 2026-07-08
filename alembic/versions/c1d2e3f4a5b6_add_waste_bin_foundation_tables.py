"""add waste bin foundation tables

Revision ID: c1d2e3f4a5b6
Revises: b9c8d7e6f5a4
Create Date: 2026-03-06 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b9c8d7e6f5a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_sites",
        sa.Column("customer_site_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=False),
        sa.Column("site_name", sa.String(), nullable=True),
        sa.Column("address_line_1", sa.String(), nullable=False),
        sa.Column("city", sa.String(), nullable=False),
        sa.Column("province", sa.String(), nullable=False),
        sa.Column("postal_code", sa.String(), nullable=False),
        sa.Column("contact_name", sa.String(), nullable=True),
        sa.Column("contact_email", sa.String(), nullable=True),
        sa.Column("contact_phone", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("customer_site_id"),
    )
    op.create_index("ix_customer_sites_company_id", "customer_sites", ["company_id"], unique=False)
    op.create_index("ix_customer_sites_address_line_1", "customer_sites", ["address_line_1"], unique=False)

    op.create_table(
        "bin_assets",
        sa.Column("bin_asset_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("bin_number", sa.String(), nullable=False),
        sa.Column("bin_type", sa.String(), nullable=False),
        sa.Column("bin_size", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="AVAILABLE", nullable=False),
        sa.Column("current_customer_site_id", sa.String(), nullable=True),
        sa.Column("current_job_purchase_order_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','ASSIGNED','OUT_OF_SERVICE')",
            name="ck_bin_assets_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["current_customer_site_id"],
            ["customer_sites.customer_site_id"],
            ondelete="RESTRICT",
            name="fk_bin_assets_current_customer_site",
        ),
        sa.ForeignKeyConstraint(
            ["current_job_purchase_order_id"],
            ["job_purchase_orders.job_purchase_order_id"],
            ondelete="RESTRICT",
            name="fk_bin_assets_current_job_po",
        ),
        sa.PrimaryKeyConstraint("bin_asset_id"),
        sa.UniqueConstraint("company_id", "bin_number", name="uq_bin_assets_company_bin_number"),
    )
    op.create_index("ix_bin_assets_company_id", "bin_assets", ["company_id"], unique=False)
    op.create_index("ix_bin_assets_bin_number", "bin_assets", ["bin_number"], unique=False)
    op.create_index("ix_bin_assets_status", "bin_assets", ["status"], unique=False)
    op.create_index("ix_bin_assets_current_customer_site_id", "bin_assets", ["current_customer_site_id"], unique=False)
    op.create_index(
        "ix_bin_assets_current_job_purchase_order_id",
        "bin_assets",
        ["current_job_purchase_order_id"],
        unique=False,
    )

    op.create_table(
        "bin_service_requests",
        sa.Column("bin_service_request_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("customer_site_id", sa.String(), nullable=False),
        sa.Column("job_purchase_order_id", sa.String(), nullable=True),
        sa.Column("source_email_ingestion_event_id", sa.String(), nullable=True),
        sa.Column("request_type", sa.String(), nullable=False),
        sa.Column("requested_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), server_default="OPEN", nullable=False),
        sa.Column("request_notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "request_type IN ('DROP','SWAP','PICKUP')",
            name="ck_bin_service_requests_request_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','SCHEDULED','COMPLETED','CANCELLED')",
            name="ck_bin_service_requests_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["customer_site_id"],
            ["customer_sites.customer_site_id"],
            ondelete="RESTRICT",
            name="fk_bin_service_requests_customer_site",
        ),
        sa.ForeignKeyConstraint(
            ["job_purchase_order_id"],
            ["job_purchase_orders.job_purchase_order_id"],
            ondelete="RESTRICT",
            name="fk_bin_service_requests_job_po",
        ),
        sa.ForeignKeyConstraint(
            ["source_email_ingestion_event_id"],
            ["email_ingestion_events.email_ingestion_event_id"],
            ondelete="RESTRICT",
            name="fk_bin_service_requests_email_ingestion",
        ),
        sa.PrimaryKeyConstraint("bin_service_request_id"),
    )
    op.create_index("ix_bin_service_requests_company_id", "bin_service_requests", ["company_id"], unique=False)
    op.create_index("ix_bin_service_requests_customer_site_id", "bin_service_requests", ["customer_site_id"], unique=False)
    op.create_index("ix_bin_service_requests_status", "bin_service_requests", ["status"], unique=False)
    op.create_index(
        "ix_bin_service_requests_job_purchase_order_id",
        "bin_service_requests",
        ["job_purchase_order_id"],
        unique=False,
    )
    op.create_index(
        "ix_bin_service_requests_source_email_ingestion_event_id",
        "bin_service_requests",
        ["source_email_ingestion_event_id"],
        unique=False,
    )

    op.create_table(
        "bin_service_tickets",
        sa.Column("bin_service_ticket_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("bin_service_request_id", sa.String(), nullable=False),
        sa.Column("customer_site_id", sa.String(), nullable=False),
        sa.Column("job_purchase_order_id", sa.String(), nullable=True),
        sa.Column("assigned_bin_asset_id", sa.String(), nullable=True),
        sa.Column("service_type", sa.String(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), server_default="OPEN", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "service_type IN ('DROP','SWAP','PICKUP')",
            name="ck_bin_service_tickets_service_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','SCHEDULED','COMPLETED','CANCELLED')",
            name="ck_bin_service_tickets_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_bin_asset_id"],
            ["bin_assets.bin_asset_id"],
            ondelete="RESTRICT",
            name="fk_bin_service_tickets_assigned_bin",
        ),
        sa.ForeignKeyConstraint(
            ["bin_service_request_id"],
            ["bin_service_requests.bin_service_request_id"],
            ondelete="RESTRICT",
            name="fk_bin_service_tickets_service_request",
        ),
        sa.ForeignKeyConstraint(
            ["customer_site_id"],
            ["customer_sites.customer_site_id"],
            ondelete="RESTRICT",
            name="fk_bin_service_tickets_customer_site",
        ),
        sa.ForeignKeyConstraint(
            ["job_purchase_order_id"],
            ["job_purchase_orders.job_purchase_order_id"],
            ondelete="RESTRICT",
            name="fk_bin_service_tickets_job_po",
        ),
        sa.PrimaryKeyConstraint("bin_service_ticket_id"),
    )
    op.create_index("ix_bin_service_tickets_company_id", "bin_service_tickets", ["company_id"], unique=False)
    op.create_index("ix_bin_service_tickets_bin_service_request_id", "bin_service_tickets", ["bin_service_request_id"], unique=False)
    op.create_index("ix_bin_service_tickets_customer_site_id", "bin_service_tickets", ["customer_site_id"], unique=False)
    op.create_index("ix_bin_service_tickets_status", "bin_service_tickets", ["status"], unique=False)
    op.create_index(
        "ix_bin_service_tickets_job_purchase_order_id",
        "bin_service_tickets",
        ["job_purchase_order_id"],
        unique=False,
    )
    op.create_index("ix_bin_service_tickets_assigned_bin_asset_id", "bin_service_tickets", ["assigned_bin_asset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bin_service_tickets_assigned_bin_asset_id", table_name="bin_service_tickets")
    op.drop_index("ix_bin_service_tickets_job_purchase_order_id", table_name="bin_service_tickets")
    op.drop_index("ix_bin_service_tickets_status", table_name="bin_service_tickets")
    op.drop_index("ix_bin_service_tickets_customer_site_id", table_name="bin_service_tickets")
    op.drop_index("ix_bin_service_tickets_bin_service_request_id", table_name="bin_service_tickets")
    op.drop_index("ix_bin_service_tickets_company_id", table_name="bin_service_tickets")
    op.drop_table("bin_service_tickets")

    op.drop_index("ix_bin_service_requests_source_email_ingestion_event_id", table_name="bin_service_requests")
    op.drop_index("ix_bin_service_requests_job_purchase_order_id", table_name="bin_service_requests")
    op.drop_index("ix_bin_service_requests_status", table_name="bin_service_requests")
    op.drop_index("ix_bin_service_requests_customer_site_id", table_name="bin_service_requests")
    op.drop_index("ix_bin_service_requests_company_id", table_name="bin_service_requests")
    op.drop_table("bin_service_requests")

    op.drop_index("ix_bin_assets_current_job_purchase_order_id", table_name="bin_assets")
    op.drop_index("ix_bin_assets_current_customer_site_id", table_name="bin_assets")
    op.drop_index("ix_bin_assets_status", table_name="bin_assets")
    op.drop_index("ix_bin_assets_bin_number", table_name="bin_assets")
    op.drop_index("ix_bin_assets_company_id", table_name="bin_assets")
    op.drop_table("bin_assets")

    op.drop_index("ix_customer_sites_address_line_1", table_name="customer_sites")
    op.drop_index("ix_customer_sites_company_id", table_name="customer_sites")
    op.drop_table("customer_sites")

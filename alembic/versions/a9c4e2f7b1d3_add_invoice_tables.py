"""add invoice tables

Revision ID: a9c4e2f7b1d3
Revises: f6d1a2b3c4e8
Create Date: 2026-03-07 12:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a9c4e2f7b1d3"
down_revision: Union[str, Sequence[str], None] = "f6d1a2b3c4e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("invoice_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=False),
        sa.Column("customer_site_id", sa.String(), nullable=False),
        sa.Column("job_purchase_order_id", sa.String(), nullable=True),
        sa.Column("service_ticket_id", sa.String(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("po_number", sa.String(), nullable=True),
        sa.Column("billing_address", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("subtotal_cents", sa.Integer(), nullable=False),
        sa.Column("tax_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('DRAFT','SENT','PAID','VOID')", name="ck_invoices_status_valid"),
        sa.ForeignKeyConstraint(["customer_site_id"], ["customer_sites.customer_site_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["job_purchase_order_id"], ["job_purchase_orders.job_purchase_order_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["service_ticket_id"], ["bin_service_tickets.bin_service_ticket_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("invoice_id"),
        sa.UniqueConstraint("company_id", "service_ticket_id", name="uq_invoices_company_service_ticket"),
    )
    op.create_index("ix_invoices_company_id", "invoices", ["company_id"], unique=False)
    op.create_index("ix_invoices_customer_site_id", "invoices", ["customer_site_id"], unique=False)
    op.create_index("ix_invoices_job_purchase_order_id", "invoices", ["job_purchase_order_id"], unique=False)
    op.create_index("ix_invoices_service_ticket_id", "invoices", ["service_ticket_id"], unique=False)
    op.create_index("ix_invoices_status", "invoices", ["status"], unique=False)

    op.create_table(
        "invoice_lines",
        sa.Column("invoice_line_id", sa.String(), nullable=False),
        sa.Column("invoice_id", sa.String(), nullable=False),
        sa.Column("line_type", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("line_total_cents", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.invoice_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("invoice_line_id"),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"], unique=False)
    op.create_index("ix_invoice_lines_line_type", "invoice_lines", ["line_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_invoice_lines_line_type", table_name="invoice_lines")
    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_table("invoice_lines")

    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_service_ticket_id", table_name="invoices")
    op.drop_index("ix_invoices_job_purchase_order_id", table_name="invoices")
    op.drop_index("ix_invoices_customer_site_id", table_name="invoices")
    op.drop_index("ix_invoices_company_id", table_name="invoices")
    op.drop_table("invoices")

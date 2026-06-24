"""add job document ingestion and purchase order tables

Revision ID: a1b2c3d4e5f7
Revises: f1b2c3d4e5f6
Create Date: 2026-03-06 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_ingestion_events",
        sa.Column("email_ingestion_event_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.String(), nullable=False),
        sa.Column("sender_email", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("parse_status", sa.String(), server_default="RECEIVED", nullable=False),
        sa.Column("parsed_job_id", sa.Integer(), nullable=True),
        sa.Column("parsed_scope_id", sa.Integer(), nullable=True),
        sa.Column("parsed_po_number", sa.String(), nullable=True),
        sa.Column("parse_notes", sa.String(), nullable=True),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "parse_status IN ('RECEIVED','PARSED','FAILED')",
            name="ck_email_ingestion_events_parse_status_valid",
        ),
        sa.PrimaryKeyConstraint("email_ingestion_event_id"),
    )

    op.create_index(
        "ix_email_ingestion_events_company_id",
        "email_ingestion_events",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_ingestion_events_source_message_id",
        "email_ingestion_events",
        ["source_message_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_ingestion_events_parse_status",
        "email_ingestion_events",
        ["parse_status"],
        unique=False,
    )
    op.create_index(
        "ix_email_ingestion_events_parsed_job_id",
        "email_ingestion_events",
        ["parsed_job_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_ingestion_events_parsed_scope_id",
        "email_ingestion_events",
        ["parsed_scope_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_ingestion_events_parsed_po_number",
        "email_ingestion_events",
        ["parsed_po_number"],
        unique=False,
    )

    op.create_table(
        "job_documents",
        sa.Column("job_document_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("email_ingestion_event_id", sa.String(), nullable=True),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=True),
        sa.Column("parsed_text", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="RESTRICT",
            name="fk_job_documents_job_id_jobs",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
            ondelete="RESTRICT",
            name="fk_job_documents_scope_id_scopes",
        ),
        sa.ForeignKeyConstraint(
            ["email_ingestion_event_id"],
            ["email_ingestion_events.email_ingestion_event_id"],
            ondelete="RESTRICT",
            name="fk_job_docs_email_ingestion_event",
        ),
        sa.PrimaryKeyConstraint("job_document_id"),
    )

    op.create_index("ix_job_documents_company_id", "job_documents", ["company_id"], unique=False)
    op.create_index("ix_job_documents_job_id", "job_documents", ["job_id"], unique=False)
    op.create_index("ix_job_documents_scope_id", "job_documents", ["scope_id"], unique=False)
    op.create_index(
        "ix_job_documents_email_ingestion_event_id",
        "job_documents",
        ["email_ingestion_event_id"],
        unique=False,
    )
    op.create_index("ix_job_documents_document_type", "job_documents", ["document_type"], unique=False)

    op.create_table(
        "job_purchase_orders",
        sa.Column("job_purchase_order_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("po_number", sa.String(), nullable=False),
        sa.Column("vendor_name", sa.String(), nullable=True),
        sa.Column("vendor_email", sa.String(), nullable=True),
        sa.Column("source_email_ingestion_event_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="DRAFT", nullable=False),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT','ISSUED','CLOSED','VOID')",
            name="ck_job_purchase_orders_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="RESTRICT",
            name="fk_job_purchase_orders_job_id_jobs",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
            ondelete="RESTRICT",
            name="fk_job_purchase_orders_scope_id_scopes",
        ),
        sa.ForeignKeyConstraint(
            ["source_email_ingestion_event_id"],
            ["email_ingestion_events.email_ingestion_event_id"],
            ondelete="RESTRICT",
            name="fk_job_pos_source_email_ingestion_event",
        ),
        sa.PrimaryKeyConstraint("job_purchase_order_id"),
        sa.UniqueConstraint("company_id", "po_number", name="uq_job_purchase_orders_company_po_number"),
    )

    op.create_index("ix_job_purchase_orders_company_id", "job_purchase_orders", ["company_id"], unique=False)
    op.create_index("ix_job_purchase_orders_job_id", "job_purchase_orders", ["job_id"], unique=False)
    op.create_index("ix_job_purchase_orders_scope_id", "job_purchase_orders", ["scope_id"], unique=False)
    op.create_index("ix_job_purchase_orders_po_number", "job_purchase_orders", ["po_number"], unique=False)
    op.create_index("ix_job_purchase_orders_status", "job_purchase_orders", ["status"], unique=False)
    op.create_index(
        "ix_job_purchase_orders_source_email_ingestion_event_id",
        "job_purchase_orders",
        ["source_email_ingestion_event_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_job_purchase_orders_source_email_ingestion_event_id", table_name="job_purchase_orders")
    op.drop_index("ix_job_purchase_orders_status", table_name="job_purchase_orders")
    op.drop_index("ix_job_purchase_orders_po_number", table_name="job_purchase_orders")
    op.drop_index("ix_job_purchase_orders_scope_id", table_name="job_purchase_orders")
    op.drop_index("ix_job_purchase_orders_job_id", table_name="job_purchase_orders")
    op.drop_index("ix_job_purchase_orders_company_id", table_name="job_purchase_orders")
    op.drop_table("job_purchase_orders")

    op.drop_index("ix_job_documents_document_type", table_name="job_documents")
    op.drop_index("ix_job_documents_email_ingestion_event_id", table_name="job_documents")
    op.drop_index("ix_job_documents_scope_id", table_name="job_documents")
    op.drop_index("ix_job_documents_job_id", table_name="job_documents")
    op.drop_index("ix_job_documents_company_id", table_name="job_documents")
    op.drop_table("job_documents")

    op.drop_index("ix_email_ingestion_events_parsed_po_number", table_name="email_ingestion_events")
    op.drop_index("ix_email_ingestion_events_parsed_scope_id", table_name="email_ingestion_events")
    op.drop_index("ix_email_ingestion_events_parsed_job_id", table_name="email_ingestion_events")
    op.drop_index("ix_email_ingestion_events_parse_status", table_name="email_ingestion_events")
    op.drop_index("ix_email_ingestion_events_source_message_id", table_name="email_ingestion_events")
    op.drop_index("ix_email_ingestion_events_company_id", table_name="email_ingestion_events")
    op.drop_table("email_ingestion_events")

"""add po ready ops records

Revision ID: f4c2b8a1d9e7
Revises: e2f4a6c8d1b3
Create Date: 2026-03-07 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4c2b8a1d9e7"
down_revision: Union[str, Sequence[str], None] = "e2f4a6c8d1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bin_service_requests",
        sa.Column("request_source", sa.String(), nullable=False, server_default="MANUAL"),
    )
    op.create_check_constraint(
        "ck_bin_service_requests_request_source_valid",
        "bin_service_requests",
        "request_source IN ('MANUAL','EMAIL_INGESTION','PO_READY_FOR_OPS')",
    )
    op.create_index(
        "ix_bin_service_requests_request_source",
        "bin_service_requests",
        ["request_source"],
        unique=False,
    )

    op.create_table(
        "foundation_work_packages",
        sa.Column("foundation_work_package_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("job_purchase_order_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="READY"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('READY','IN_PROGRESS','COMPLETED','CANCELLED')",
            name="ck_foundation_work_packages_status_valid",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["job_purchase_order_id"],
            ["job_purchase_orders.job_purchase_order_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("foundation_work_package_id"),
        sa.UniqueConstraint("company_id", "job_purchase_order_id", name="uq_foundation_work_packages_company_po_id"),
    )
    op.create_index("ix_foundation_work_packages_company_id", "foundation_work_packages", ["company_id"], unique=False)
    op.create_index("ix_foundation_work_packages_job_id", "foundation_work_packages", ["job_id"], unique=False)
    op.create_index("ix_foundation_work_packages_scope_id", "foundation_work_packages", ["scope_id"], unique=False)
    op.create_index(
        "ix_foundation_work_packages_job_purchase_order_id",
        "foundation_work_packages",
        ["job_purchase_order_id"],
        unique=False,
    )
    op.create_index("ix_foundation_work_packages_status", "foundation_work_packages", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_foundation_work_packages_status", table_name="foundation_work_packages")
    op.drop_index("ix_foundation_work_packages_job_purchase_order_id", table_name="foundation_work_packages")
    op.drop_index("ix_foundation_work_packages_scope_id", table_name="foundation_work_packages")
    op.drop_index("ix_foundation_work_packages_job_id", table_name="foundation_work_packages")
    op.drop_index("ix_foundation_work_packages_company_id", table_name="foundation_work_packages")
    op.drop_table("foundation_work_packages")

    op.drop_index("ix_bin_service_requests_request_source", table_name="bin_service_requests")
    op.drop_constraint(
        "ck_bin_service_requests_request_source_valid",
        "bin_service_requests",
        type_="check",
    )
    op.drop_column("bin_service_requests", "request_source")

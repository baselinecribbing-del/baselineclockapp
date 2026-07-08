"""add po queue review fields

Revision ID: e2f4a6c8d1b3
Revises: d5b8c2a4e1f9
Create Date: 2026-03-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2f4a6c8d1b3"
down_revision: Union[str, Sequence[str], None] = "d5b8c2a4e1f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_purchase_orders",
        sa.Column("queue_status", sa.String(), nullable=False, server_default="RECEIVED"),
    )
    op.add_column("job_purchase_orders", sa.Column("matched_job_id", sa.Integer(), nullable=True))
    op.add_column("job_purchase_orders", sa.Column("matched_scope_id", sa.Integer(), nullable=True))
    op.add_column("job_purchase_orders", sa.Column("matched_customer_site_id", sa.String(), nullable=True))
    op.add_column("job_purchase_orders", sa.Column("reviewed_by_user_id", sa.String(), nullable=True))
    op.add_column("job_purchase_orders", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_purchase_orders", sa.Column("review_notes", sa.String(), nullable=True))

    op.create_check_constraint(
        "ck_job_purchase_orders_queue_status_valid",
        "job_purchase_orders",
        "queue_status IN ('RECEIVED','UNMATCHED','MATCHED','READY_FOR_OPS','CLOSED')",
    )

    op.create_index("ix_job_purchase_orders_queue_status", "job_purchase_orders", ["queue_status"], unique=False)
    op.create_index("ix_job_purchase_orders_matched_job_id", "job_purchase_orders", ["matched_job_id"], unique=False)
    op.create_index("ix_job_purchase_orders_matched_scope_id", "job_purchase_orders", ["matched_scope_id"], unique=False)
    op.create_index(
        "ix_job_purchase_orders_matched_customer_site_id",
        "job_purchase_orders",
        ["matched_customer_site_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_job_purchase_orders_matched_job_id_jobs",
        "job_purchase_orders",
        "jobs",
        ["matched_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_job_purchase_orders_matched_scope_id_scopes",
        "job_purchase_orders",
        "scopes",
        ["matched_scope_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_job_purchase_orders_matched_customer_site_id_customer_sites",
        "job_purchase_orders",
        "customer_sites",
        ["matched_customer_site_id"],
        ["customer_site_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_job_purchase_orders_matched_customer_site_id_customer_sites",
        "job_purchase_orders",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_job_purchase_orders_matched_scope_id_scopes",
        "job_purchase_orders",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_job_purchase_orders_matched_job_id_jobs",
        "job_purchase_orders",
        type_="foreignkey",
    )

    op.drop_index("ix_job_purchase_orders_matched_customer_site_id", table_name="job_purchase_orders")
    op.drop_index("ix_job_purchase_orders_matched_scope_id", table_name="job_purchase_orders")
    op.drop_index("ix_job_purchase_orders_matched_job_id", table_name="job_purchase_orders")
    op.drop_index("ix_job_purchase_orders_queue_status", table_name="job_purchase_orders")

    op.drop_constraint("ck_job_purchase_orders_queue_status_valid", "job_purchase_orders", type_="check")

    op.drop_column("job_purchase_orders", "review_notes")
    op.drop_column("job_purchase_orders", "reviewed_at")
    op.drop_column("job_purchase_orders", "reviewed_by_user_id")
    op.drop_column("job_purchase_orders", "matched_customer_site_id")
    op.drop_column("job_purchase_orders", "matched_scope_id")
    op.drop_column("job_purchase_orders", "matched_job_id")
    op.drop_column("job_purchase_orders", "queue_status")

"""add job start intakes

Revision ID: 4c1d2e3f4a5b
Revises: 3b9e2c1d4f6a
Create Date: 2026-03-09 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4c1d2e3f4a5b"
down_revision: Union[str, Sequence[str], None] = "3b9e2c1d4f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_start_intakes",
        sa.Column("job_start_intake_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("email_ingestion_event_id", sa.String(), nullable=False),
        sa.Column("duplicate_of_job_start_intake_id", sa.String(), nullable=True),
        sa.Column("builder_name", sa.String(), nullable=True),
        sa.Column("source_email", sa.String(), nullable=False),
        sa.Column("project_address", sa.String(), nullable=True),
        sa.Column("lot_number", sa.String(), nullable=True),
        sa.Column("block_number", sa.String(), nullable=True),
        sa.Column("stake_date", sa.Date(), nullable=True),
        sa.Column("intake_status", sa.String(), server_default="FLAGGED", nullable=False),
        sa.Column("has_blueprint", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("has_grade_slip", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("has_site_plan", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("has_stake_date_document", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("parse_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "intake_status IN ('QUEUED','FLAGGED','DUPLICATE')",
            name="ck_job_start_intakes_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_job_start_intake_id"],
            ["job_start_intakes.job_start_intake_id"],
            ondelete="RESTRICT",
            name="fk_job_start_intakes_duplicate_of",
        ),
        sa.ForeignKeyConstraint(
            ["email_ingestion_event_id"],
            ["email_ingestion_events.email_ingestion_event_id"],
            ondelete="RESTRICT",
            name="fk_job_start_intakes_email_ingestion_event",
        ),
        sa.PrimaryKeyConstraint("job_start_intake_id"),
        sa.UniqueConstraint(
            "company_id",
            "email_ingestion_event_id",
            name="uq_job_start_intakes_company_email_event",
        ),
    )

    op.create_index("ix_job_start_intakes_company_id", "job_start_intakes", ["company_id"], unique=False)
    op.create_index(
        "ix_job_start_intakes_email_ingestion_event_id",
        "job_start_intakes",
        ["email_ingestion_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_start_intakes_duplicate_of_job_start_intake_id",
        "job_start_intakes",
        ["duplicate_of_job_start_intake_id"],
        unique=False,
    )
    op.create_index("ix_job_start_intakes_builder_name", "job_start_intakes", ["builder_name"], unique=False)
    op.create_index("ix_job_start_intakes_project_address", "job_start_intakes", ["project_address"], unique=False)
    op.create_index("ix_job_start_intakes_stake_date", "job_start_intakes", ["stake_date"], unique=False)
    op.create_index("ix_job_start_intakes_intake_status", "job_start_intakes", ["intake_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_start_intakes_intake_status", table_name="job_start_intakes")
    op.drop_index("ix_job_start_intakes_stake_date", table_name="job_start_intakes")
    op.drop_index("ix_job_start_intakes_project_address", table_name="job_start_intakes")
    op.drop_index("ix_job_start_intakes_builder_name", table_name="job_start_intakes")
    op.drop_index("ix_job_start_intakes_duplicate_of_job_start_intake_id", table_name="job_start_intakes")
    op.drop_index("ix_job_start_intakes_email_ingestion_event_id", table_name="job_start_intakes")
    op.drop_index("ix_job_start_intakes_company_id", table_name="job_start_intakes")
    op.drop_table("job_start_intakes")

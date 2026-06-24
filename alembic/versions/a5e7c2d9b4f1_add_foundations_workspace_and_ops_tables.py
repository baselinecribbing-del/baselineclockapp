"""add foundations workspace and operations tables

Revision ID: a5e7c2d9b4f1
Revises: fa3b2c1d4e6f
Create Date: 2026-03-07 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a5e7c2d9b4f1"
down_revision: Union[str, Sequence[str], None] = "fa3b2c1d4e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_modules",
        sa.Column("company_module_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("module_code", sa.String(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "module_code IN ('FOUNDATIONS','WASTE_BINS')",
            name="ck_company_modules_module_code_valid",
        ),
        sa.PrimaryKeyConstraint("company_module_id"),
        sa.UniqueConstraint("company_id", "module_code", name="uq_company_modules_company_module_code"),
    )
    op.create_index("ix_company_modules_company_id", "company_modules", ["company_id"], unique=False)
    op.create_index("ix_company_modules_module_code", "company_modules", ["module_code"], unique=False)

    op.create_table(
        "crew_assignments",
        sa.Column("crew_assignment_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("assigned_date", sa.Date(), nullable=False),
        sa.Column("assigned_by_user_id", sa.String(), nullable=False),
        sa.Column("assignment_notes", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="ASSIGNED", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('ASSIGNED','ACKNOWLEDGED','COMPLETED','CANCELLED')",
            name="ck_crew_assignments_status_valid",
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT", name="fk_crew_assignments_employee"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT", name="fk_crew_assignments_job"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="RESTRICT", name="fk_crew_assignments_scope"),
        sa.PrimaryKeyConstraint("crew_assignment_id"),
    )
    op.create_index("ix_crew_assignments_company_id", "crew_assignments", ["company_id"], unique=False)
    op.create_index("ix_crew_assignments_employee_id", "crew_assignments", ["employee_id"], unique=False)
    op.create_index("ix_crew_assignments_job_id", "crew_assignments", ["job_id"], unique=False)
    op.create_index("ix_crew_assignments_scope_id", "crew_assignments", ["scope_id"], unique=False)
    op.create_index("ix_crew_assignments_assigned_date", "crew_assignments", ["assigned_date"], unique=False)
    op.create_index("ix_crew_assignments_status", "crew_assignments", ["status"], unique=False)

    op.create_table(
        "hazard_assessments",
        sa.Column("hazard_assessment_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("crew_assignment_id", sa.String(), nullable=True),
        sa.Column("completed_by_employee_id", sa.Integer(), nullable=False),
        sa.Column("assessment_date", sa.Date(), nullable=False),
        sa.Column("form_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT", name="fk_hazard_assessments_job"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="RESTRICT", name="fk_hazard_assessments_scope"),
        sa.ForeignKeyConstraint(
            ["crew_assignment_id"],
            ["crew_assignments.crew_assignment_id"],
            ondelete="RESTRICT",
            name="fk_hazard_assessments_crew_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
            name="fk_hazard_assessments_completed_employee",
        ),
        sa.PrimaryKeyConstraint("hazard_assessment_id"),
    )
    op.create_index("ix_hazard_assessments_company_id", "hazard_assessments", ["company_id"], unique=False)
    op.create_index("ix_hazard_assessments_job_id", "hazard_assessments", ["job_id"], unique=False)
    op.create_index("ix_hazard_assessments_scope_id", "hazard_assessments", ["scope_id"], unique=False)
    op.create_index(
        "ix_hazard_assessments_completed_by_employee_id",
        "hazard_assessments",
        ["completed_by_employee_id"],
        unique=False,
    )
    op.create_index("ix_hazard_assessments_assessment_date", "hazard_assessments", ["assessment_date"], unique=False)

    op.create_table(
        "toolbox_meetings",
        sa.Column("toolbox_meeting_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("meeting_date", sa.Date(), nullable=False),
        sa.Column("completed_by_employee_id", sa.Integer(), nullable=False),
        sa.Column("attendee_count", sa.Integer(), nullable=True),
        sa.Column("form_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attendee_count IS NULL OR attendee_count >= 0", name="ck_toolbox_meetings_attendee_count_nonnegative"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT", name="fk_toolbox_meetings_job"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="RESTRICT", name="fk_toolbox_meetings_scope"),
        sa.ForeignKeyConstraint(
            ["completed_by_employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
            name="fk_toolbox_meetings_completed_employee",
        ),
        sa.PrimaryKeyConstraint("toolbox_meeting_id"),
    )
    op.create_index("ix_toolbox_meetings_company_id", "toolbox_meetings", ["company_id"], unique=False)
    op.create_index("ix_toolbox_meetings_job_id", "toolbox_meetings", ["job_id"], unique=False)
    op.create_index("ix_toolbox_meetings_scope_id", "toolbox_meetings", ["scope_id"], unique=False)
    op.create_index("ix_toolbox_meetings_meeting_date", "toolbox_meetings", ["meeting_date"], unique=False)

    op.create_table(
        "job_document_deliveries",
        sa.Column("job_document_delivery_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_document_id", sa.String(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_document_id"],
            ["job_documents.job_document_id"],
            ondelete="RESTRICT",
            name="fk_job_document_deliveries_job_document",
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT", name="fk_job_document_deliveries_employee"),
        sa.PrimaryKeyConstraint("job_document_delivery_id"),
    )
    op.create_index("ix_job_document_deliveries_company_id", "job_document_deliveries", ["company_id"], unique=False)
    op.create_index("ix_job_document_deliveries_job_document_id", "job_document_deliveries", ["job_document_id"], unique=False)
    op.create_index("ix_job_document_deliveries_employee_id", "job_document_deliveries", ["employee_id"], unique=False)
    op.create_index("ix_job_document_deliveries_delivered_at", "job_document_deliveries", ["delivered_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_document_deliveries_delivered_at", table_name="job_document_deliveries")
    op.drop_index("ix_job_document_deliveries_employee_id", table_name="job_document_deliveries")
    op.drop_index("ix_job_document_deliveries_job_document_id", table_name="job_document_deliveries")
    op.drop_index("ix_job_document_deliveries_company_id", table_name="job_document_deliveries")
    op.drop_table("job_document_deliveries")

    op.drop_index("ix_toolbox_meetings_meeting_date", table_name="toolbox_meetings")
    op.drop_index("ix_toolbox_meetings_scope_id", table_name="toolbox_meetings")
    op.drop_index("ix_toolbox_meetings_job_id", table_name="toolbox_meetings")
    op.drop_index("ix_toolbox_meetings_company_id", table_name="toolbox_meetings")
    op.drop_table("toolbox_meetings")

    op.drop_index("ix_hazard_assessments_assessment_date", table_name="hazard_assessments")
    op.drop_index("ix_hazard_assessments_completed_by_employee_id", table_name="hazard_assessments")
    op.drop_index("ix_hazard_assessments_scope_id", table_name="hazard_assessments")
    op.drop_index("ix_hazard_assessments_job_id", table_name="hazard_assessments")
    op.drop_index("ix_hazard_assessments_company_id", table_name="hazard_assessments")
    op.drop_table("hazard_assessments")

    op.drop_index("ix_crew_assignments_status", table_name="crew_assignments")
    op.drop_index("ix_crew_assignments_assigned_date", table_name="crew_assignments")
    op.drop_index("ix_crew_assignments_scope_id", table_name="crew_assignments")
    op.drop_index("ix_crew_assignments_job_id", table_name="crew_assignments")
    op.drop_index("ix_crew_assignments_employee_id", table_name="crew_assignments")
    op.drop_index("ix_crew_assignments_company_id", table_name="crew_assignments")
    op.drop_table("crew_assignments")

    op.drop_index("ix_company_modules_module_code", table_name="company_modules")
    op.drop_index("ix_company_modules_company_id", table_name="company_modules")
    op.drop_table("company_modules")

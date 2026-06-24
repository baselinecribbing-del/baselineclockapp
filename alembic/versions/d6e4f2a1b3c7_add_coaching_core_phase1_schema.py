"""add coaching core phase 1 schema

Revision ID: d6e4f2a1b3c7
Revises: c6e9b7d4a1f2
Create Date: 2026-03-13 09:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d6e4f2a1b3c7"
down_revision: Union[str, Sequence[str], None] = "c6e9b7d4a1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


tenant_membership_role_enum = postgresql.ENUM(
    "OWNER",
    "ADMIN",
    "TRAINER",
    "STAFF",
    name="tenant_membership_role_enum",
    create_type=False,
)
tenant_membership_status_enum = postgresql.ENUM(
    "INVITED",
    "ACTIVE",
    "SUSPENDED",
    "REMOVED",
    name="tenant_membership_status_enum",
    create_type=False,
)
client_status_enum = postgresql.ENUM(
    "ACTIVE",
    "PAUSED",
    "ARCHIVED",
    name="client_status_enum",
    create_type=False,
)
program_template_status_enum = postgresql.ENUM(
    "DRAFT",
    "ACTIVE",
    "ARCHIVED",
    name="program_template_status_enum",
    create_type=False,
)
client_program_status_enum = postgresql.ENUM(
    "DRAFT",
    "ACTIVE",
    "PAUSED",
    "COMPLETED",
    "ARCHIVED",
    name="client_program_status_enum",
    create_type=False,
)
program_day_completion_status_enum = postgresql.ENUM(
    "NOT_STARTED",
    "IN_PROGRESS",
    "COMPLETED",
    "SKIPPED",
    name="program_day_completion_status_enum",
    create_type=False,
)
exercise_media_type_enum = postgresql.ENUM(
    "IMAGE",
    "VIDEO",
    "FILE",
    name="exercise_media_type_enum",
    create_type=False,
)


def _uuid_pk(name: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=sa.text("gen_random_uuid()"),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    bind = op.get_bind()
    for enum_type in (
        tenant_membership_role_enum,
        tenant_membership_status_enum,
        client_status_enum,
        program_template_status_enum,
        client_program_status_enum,
        program_day_completion_status_enum,
        exercise_media_type_enum,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "tenants",
        _uuid_pk("tenant_id"),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_tenants_name_not_blank"),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'", name="ck_tenants_slug_format"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "users",
        _uuid_pk("user_id"),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("position('@' in email) > 1", name="ck_users_email_basic"),
        sa.CheckConstraint("btrim(full_name) <> ''", name="ck_users_full_name_not_blank"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "tenant_memberships",
        _uuid_pk("tenant_membership_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", tenant_membership_role_enum, nullable=False, server_default=sa.text("'TRAINER'")),
        sa.Column("status", tenant_membership_status_enum, nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )
    op.create_index("ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"], unique=False)
    op.create_index("ix_tenant_memberships_tenant_status", "tenant_memberships", ["tenant_id", "status"], unique=False)

    op.create_table(
        "client_profiles",
        _uuid_pk("client_profile_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primary_trainer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", client_status_enum, nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("first_name", sa.String(length=120), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("intake_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("btrim(first_name) <> ''", name="ck_client_profiles_first_name_not_blank"),
        sa.CheckConstraint("btrim(last_name) <> ''", name="ck_client_profiles_last_name_not_blank"),
        sa.ForeignKeyConstraint(["primary_trainer_user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_client_profiles_tenant_email"),
    )
    op.create_index("ix_client_profiles_tenant_id", "client_profiles", ["tenant_id"], unique=False)
    op.create_index("ix_client_profiles_primary_trainer_user_id", "client_profiles", ["primary_trainer_user_id"], unique=False)
    op.create_index("ix_client_profiles_tenant_status", "client_profiles", ["tenant_id", "status"], unique=False)

    op.create_table(
        "exercises",
        _uuid_pk("exercise_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=96), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("coaching_notes", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_exercises_name_not_blank"),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'", name="ck_exercises_slug_format"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_exercises_tenant_slug"),
    )
    op.create_index("ix_exercises_tenant_id", "exercises", ["tenant_id"], unique=False)
    op.create_index("ix_exercises_created_by_user_id", "exercises", ["created_by_user_id"], unique=False)
    op.create_index("ix_exercises_tenant_archived", "exercises", ["tenant_id", "is_archived"], unique=False)

    op.create_table(
        "exercise_media",
        _uuid_pk("exercise_media_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_type", exercise_media_type_enum, nullable=False),
        sa.Column("storage_url", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sort_order >= 1", name="ck_exercise_media_sort_order_positive"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.exercise_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exercise_id", "sort_order", name="uq_exercise_media_exercise_sort_order"),
    )
    op.create_index("ix_exercise_media_tenant_id", "exercise_media", ["tenant_id"], unique=False)
    op.create_index("ix_exercise_media_exercise_id", "exercise_media", ["exercise_id"], unique=False)

    op.create_table(
        "program_templates",
        _uuid_pk("program_template_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("status", program_template_status_enum, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_program_templates_name_not_blank"),
        sa.CheckConstraint("version >= 1", name="ck_program_templates_version_positive"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "name", "version", name="uq_program_templates_tenant_name_version"),
    )
    op.create_index("ix_program_templates_tenant_id", "program_templates", ["tenant_id"], unique=False)
    op.create_index("ix_program_templates_created_by_user_id", "program_templates", ["created_by_user_id"], unique=False)
    op.create_index("ix_program_templates_tenant_status", "program_templates", ["tenant_id", "status"], unique=False)

    op.create_table(
        "program_template_weeks",
        _uuid_pk("program_template_week_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("week_number >= 1", name="ck_program_template_weeks_week_number_positive"),
        sa.ForeignKeyConstraint(["program_template_id"], ["program_templates.program_template_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("program_template_id", "week_number", name="uq_program_template_weeks_template_week"),
    )
    op.create_index("ix_program_template_weeks_tenant_id", "program_template_weeks", ["tenant_id"], unique=False)
    op.create_index("ix_program_template_weeks_program_template_id", "program_template_weeks", ["program_template_id"], unique=False)

    op.create_table(
        "program_template_days",
        _uuid_pk("program_template_day_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_template_week_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("day_number >= 1", name="ck_program_template_days_day_number_positive"),
        sa.ForeignKeyConstraint(["program_template_week_id"], ["program_template_weeks.program_template_week_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("program_template_week_id", "day_number", name="uq_program_template_days_week_day"),
    )
    op.create_index("ix_program_template_days_tenant_id", "program_template_days", ["tenant_id"], unique=False)
    op.create_index("ix_program_template_days_program_template_week_id", "program_template_days", ["program_template_week_id"], unique=False)

    op.create_table(
        "program_template_exercises",
        _uuid_pk("program_template_exercise_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_template_day_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("exercise_name_override", sa.String(length=255), nullable=True),
        sa.Column("sets_text", sa.String(length=64), nullable=True),
        sa.Column("reps_text", sa.String(length=64), nullable=True),
        sa.Column("load_text", sa.String(length=64), nullable=True),
        sa.Column("rest_text", sa.String(length=64), nullable=True),
        sa.Column("tempo_text", sa.String(length=64), nullable=True),
        sa.Column("rir_text", sa.String(length=64), nullable=True),
        sa.Column("duration_text", sa.String(length=64), nullable=True),
        sa.Column("distance_text", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("prescription", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sort_order >= 1", name="ck_program_template_exercises_sort_order_positive"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.exercise_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["program_template_day_id"], ["program_template_days.program_template_day_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("program_template_day_id", "sort_order", name="uq_program_template_exercises_day_sort"),
    )
    op.create_index("ix_program_template_exercises_tenant_id", "program_template_exercises", ["tenant_id"], unique=False)
    op.create_index("ix_program_template_exercises_program_template_day_id", "program_template_exercises", ["program_template_day_id"], unique=False)
    op.create_index("ix_program_template_exercises_exercise_id", "program_template_exercises", ["exercise_id"], unique=False)

    op.create_table(
        "client_programs",
        _uuid_pk("client_program_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_program_template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("status", client_program_status_enum, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_client_programs_name_not_blank"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_profile_id"], ["client_profiles.client_profile_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_program_template_id"], ["program_templates.program_template_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_client_programs_tenant_id", "client_programs", ["tenant_id"], unique=False)
    op.create_index("ix_client_programs_client_profile_id", "client_programs", ["client_profile_id"], unique=False)
    op.create_index("ix_client_programs_assigned_by_user_id", "client_programs", ["assigned_by_user_id"], unique=False)
    op.create_index("ix_client_programs_source_program_template_id", "client_programs", ["source_program_template_id"], unique=False)
    op.create_index("ix_client_programs_tenant_client_status", "client_programs", ["tenant_id", "client_profile_id", "status"], unique=False)

    op.create_table(
        "client_program_weeks",
        _uuid_pk("client_program_week_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("week_number >= 1", name="ck_client_program_weeks_week_number_positive"),
        sa.ForeignKeyConstraint(["client_program_id"], ["client_programs.client_program_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("client_program_id", "week_number", name="uq_client_program_weeks_program_week"),
    )
    op.create_index("ix_client_program_weeks_tenant_id", "client_program_weeks", ["tenant_id"], unique=False)
    op.create_index("ix_client_program_weeks_client_program_id", "client_program_weeks", ["client_program_id"], unique=False)

    op.create_table(
        "client_program_days",
        _uuid_pk("client_program_day_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_program_week_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("status", program_day_completion_status_enum, nullable=False, server_default=sa.text("'NOT_STARTED'")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("day_number >= 1", name="ck_client_program_days_day_number_positive"),
        sa.ForeignKeyConstraint(["client_program_week_id"], ["client_program_weeks.client_program_week_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("client_program_week_id", "day_number", name="uq_client_program_days_week_day"),
    )
    op.create_index("ix_client_program_days_tenant_id", "client_program_days", ["tenant_id"], unique=False)
    op.create_index("ix_client_program_days_client_program_week_id", "client_program_days", ["client_program_week_id"], unique=False)
    op.create_index("ix_client_program_days_tenant_status", "client_program_days", ["tenant_id", "status"], unique=False)

    op.create_table(
        "client_program_exercises",
        _uuid_pk("client_program_exercise_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_program_day_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_program_template_exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("exercise_name", sa.String(length=255), nullable=False),
        sa.Column("sets_text", sa.String(length=64), nullable=True),
        sa.Column("reps_text", sa.String(length=64), nullable=True),
        sa.Column("load_text", sa.String(length=64), nullable=True),
        sa.Column("rest_text", sa.String(length=64), nullable=True),
        sa.Column("tempo_text", sa.String(length=64), nullable=True),
        sa.Column("rir_text", sa.String(length=64), nullable=True),
        sa.Column("duration_text", sa.String(length=64), nullable=True),
        sa.Column("distance_text", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("prescription", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sort_order >= 1", name="ck_client_program_exercises_sort_order_positive"),
        sa.CheckConstraint("btrim(exercise_name) <> ''", name="ck_client_program_exercises_name_not_blank"),
        sa.ForeignKeyConstraint(["client_program_day_id"], ["client_program_days.client_program_day_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.exercise_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_program_template_exercise_id"], ["program_template_exercises.program_template_exercise_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("client_program_day_id", "sort_order", name="uq_client_program_exercises_day_sort"),
    )
    op.create_index("ix_client_program_exercises_tenant_id", "client_program_exercises", ["tenant_id"], unique=False)
    op.create_index("ix_client_program_exercises_client_program_day_id", "client_program_exercises", ["client_program_day_id"], unique=False)
    op.create_index("ix_client_program_exercises_source_program_template_exercise_id", "client_program_exercises", ["source_program_template_exercise_id"], unique=False)
    op.create_index("ix_client_program_exercises_exercise_id", "client_program_exercises", ["exercise_id"], unique=False)

    op.create_table(
        "workout_logs",
        _uuid_pk("workout_log_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_program_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_program_day_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("logged_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_profile_id"], ["client_profiles.client_profile_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_program_day_id"], ["client_program_days.client_program_day_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_program_id"], ["client_programs.client_program_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["logged_by_user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workout_logs_tenant_id", "workout_logs", ["tenant_id"], unique=False)
    op.create_index("ix_workout_logs_client_profile_id", "workout_logs", ["client_profile_id"], unique=False)
    op.create_index("ix_workout_logs_client_program_id", "workout_logs", ["client_program_id"], unique=False)
    op.create_index("ix_workout_logs_client_program_day_id", "workout_logs", ["client_program_day_id"], unique=False)
    op.create_index("ix_workout_logs_logged_by_user_id", "workout_logs", ["logged_by_user_id"], unique=False)
    op.create_index("ix_workout_logs_performed_at", "workout_logs", ["performed_at"], unique=False)
    op.create_index("ix_workout_logs_tenant_client_performed", "workout_logs", ["tenant_id", "client_profile_id", "performed_at"], unique=False)

    op.create_table(
        "workout_log_exercises",
        _uuid_pk("workout_log_exercise_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workout_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_program_exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("exercise_name", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sort_order >= 1", name="ck_workout_log_exercises_sort_order_positive"),
        sa.CheckConstraint("btrim(exercise_name) <> ''", name="ck_workout_log_exercises_name_not_blank"),
        sa.ForeignKeyConstraint(["client_program_exercise_id"], ["client_program_exercises.client_program_exercise_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.exercise_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workout_log_id"], ["workout_logs.workout_log_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workout_log_id", "sort_order", name="uq_workout_log_exercises_log_sort"),
    )
    op.create_index("ix_workout_log_exercises_tenant_id", "workout_log_exercises", ["tenant_id"], unique=False)
    op.create_index("ix_workout_log_exercises_workout_log_id", "workout_log_exercises", ["workout_log_id"], unique=False)
    op.create_index("ix_workout_log_exercises_client_program_exercise_id", "workout_log_exercises", ["client_program_exercise_id"], unique=False)
    op.create_index("ix_workout_log_exercises_exercise_id", "workout_log_exercises", ["exercise_id"], unique=False)

    op.create_table(
        "workout_log_sets",
        _uuid_pk("workout_log_set_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workout_log_exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("reps_text", sa.String(length=64), nullable=True),
        sa.Column("load_text", sa.String(length=64), nullable=True),
        sa.Column("duration_text", sa.String(length=64), nullable=True),
        sa.Column("distance_text", sa.String(length=64), nullable=True),
        sa.Column("effort_text", sa.String(length=64), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("set_number >= 1", name="ck_workout_log_sets_set_number_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workout_log_exercise_id"], ["workout_log_exercises.workout_log_exercise_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workout_log_exercise_id", "set_number", name="uq_workout_log_sets_exercise_set"),
    )
    op.create_index("ix_workout_log_sets_tenant_id", "workout_log_sets", ["tenant_id"], unique=False)
    op.create_index("ix_workout_log_sets_workout_log_exercise_id", "workout_log_sets", ["workout_log_exercise_id"], unique=False)

    op.create_table(
        "audit_events",
        _uuid_pk("audit_event_id"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("btrim(entity_type) <> ''", name="ck_audit_events_entity_type_not_blank"),
        sa.CheckConstraint("btrim(action) <> ''", name="ck_audit_events_action_not_blank"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"], unique=False)
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"], unique=False)
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"], unique=False)
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"], unique=False)
    op.create_index("ix_audit_events_tenant_entity_occurred", "audit_events", ["tenant_id", "entity_type", "entity_id", "occurred_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_events_tenant_entity_occurred", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_workout_log_sets_workout_log_exercise_id", table_name="workout_log_sets")
    op.drop_index("ix_workout_log_sets_tenant_id", table_name="workout_log_sets")
    op.drop_table("workout_log_sets")

    op.drop_index("ix_workout_log_exercises_exercise_id", table_name="workout_log_exercises")
    op.drop_index("ix_workout_log_exercises_client_program_exercise_id", table_name="workout_log_exercises")
    op.drop_index("ix_workout_log_exercises_workout_log_id", table_name="workout_log_exercises")
    op.drop_index("ix_workout_log_exercises_tenant_id", table_name="workout_log_exercises")
    op.drop_table("workout_log_exercises")

    op.drop_index("ix_workout_logs_tenant_client_performed", table_name="workout_logs")
    op.drop_index("ix_workout_logs_performed_at", table_name="workout_logs")
    op.drop_index("ix_workout_logs_logged_by_user_id", table_name="workout_logs")
    op.drop_index("ix_workout_logs_client_program_day_id", table_name="workout_logs")
    op.drop_index("ix_workout_logs_client_program_id", table_name="workout_logs")
    op.drop_index("ix_workout_logs_client_profile_id", table_name="workout_logs")
    op.drop_index("ix_workout_logs_tenant_id", table_name="workout_logs")
    op.drop_table("workout_logs")

    op.drop_index("ix_client_program_exercises_exercise_id", table_name="client_program_exercises")
    op.drop_index("ix_client_program_exercises_source_program_template_exercise_id", table_name="client_program_exercises")
    op.drop_index("ix_client_program_exercises_client_program_day_id", table_name="client_program_exercises")
    op.drop_index("ix_client_program_exercises_tenant_id", table_name="client_program_exercises")
    op.drop_table("client_program_exercises")

    op.drop_index("ix_client_program_days_tenant_status", table_name="client_program_days")
    op.drop_index("ix_client_program_days_client_program_week_id", table_name="client_program_days")
    op.drop_index("ix_client_program_days_tenant_id", table_name="client_program_days")
    op.drop_table("client_program_days")

    op.drop_index("ix_client_program_weeks_client_program_id", table_name="client_program_weeks")
    op.drop_index("ix_client_program_weeks_tenant_id", table_name="client_program_weeks")
    op.drop_table("client_program_weeks")

    op.drop_index("ix_client_programs_tenant_client_status", table_name="client_programs")
    op.drop_index("ix_client_programs_source_program_template_id", table_name="client_programs")
    op.drop_index("ix_client_programs_assigned_by_user_id", table_name="client_programs")
    op.drop_index("ix_client_programs_client_profile_id", table_name="client_programs")
    op.drop_index("ix_client_programs_tenant_id", table_name="client_programs")
    op.drop_table("client_programs")

    op.drop_index("ix_program_template_exercises_exercise_id", table_name="program_template_exercises")
    op.drop_index("ix_program_template_exercises_program_template_day_id", table_name="program_template_exercises")
    op.drop_index("ix_program_template_exercises_tenant_id", table_name="program_template_exercises")
    op.drop_table("program_template_exercises")

    op.drop_index("ix_program_template_days_program_template_week_id", table_name="program_template_days")
    op.drop_index("ix_program_template_days_tenant_id", table_name="program_template_days")
    op.drop_table("program_template_days")

    op.drop_index("ix_program_template_weeks_program_template_id", table_name="program_template_weeks")
    op.drop_index("ix_program_template_weeks_tenant_id", table_name="program_template_weeks")
    op.drop_table("program_template_weeks")

    op.drop_index("ix_program_templates_tenant_status", table_name="program_templates")
    op.drop_index("ix_program_templates_created_by_user_id", table_name="program_templates")
    op.drop_index("ix_program_templates_tenant_id", table_name="program_templates")
    op.drop_table("program_templates")

    op.drop_index("ix_exercise_media_exercise_id", table_name="exercise_media")
    op.drop_index("ix_exercise_media_tenant_id", table_name="exercise_media")
    op.drop_table("exercise_media")

    op.drop_index("ix_exercises_tenant_archived", table_name="exercises")
    op.drop_index("ix_exercises_created_by_user_id", table_name="exercises")
    op.drop_index("ix_exercises_tenant_id", table_name="exercises")
    op.drop_table("exercises")

    op.drop_index("ix_client_profiles_tenant_status", table_name="client_profiles")
    op.drop_index("ix_client_profiles_primary_trainer_user_id", table_name="client_profiles")
    op.drop_index("ix_client_profiles_tenant_id", table_name="client_profiles")
    op.drop_table("client_profiles")

    op.drop_index("ix_tenant_memberships_tenant_status", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_tenant_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")

    bind = op.get_bind()
    for enum_type in (
        exercise_media_type_enum,
        program_day_completion_status_enum,
        client_program_status_enum,
        program_template_status_enum,
        client_status_enum,
        tenant_membership_status_enum,
        tenant_membership_role_enum,
    ):
        enum_type.drop(bind, checkfirst=True)

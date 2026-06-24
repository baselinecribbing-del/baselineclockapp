import enum
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList

from app.database import Base


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class TenantMembershipRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    TRAINER = "TRAINER"
    STAFF = "STAFF"


class TenantMembershipStatus(str, enum.Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class ClientStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class ProgramTemplateStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ClientProgramStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class ProgramDayCompletionStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class ExerciseMediaType(str, enum.Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    FILE = "FILE"


tenant_membership_role_enum = Enum(
    TenantMembershipRole,
    name="tenant_membership_role_enum",
    values_callable=_enum_values,
)
tenant_membership_status_enum = Enum(
    TenantMembershipStatus,
    name="tenant_membership_status_enum",
    values_callable=_enum_values,
)
client_status_enum = Enum(
    ClientStatus,
    name="client_status_enum",
    values_callable=_enum_values,
)
program_template_status_enum = Enum(
    ProgramTemplateStatus,
    name="program_template_status_enum",
    values_callable=_enum_values,
)
client_program_status_enum = Enum(
    ClientProgramStatus,
    name="client_program_status_enum",
    values_callable=_enum_values,
)
program_day_completion_status_enum = Enum(
    ProgramDayCompletionStatus,
    name="program_day_completion_status_enum",
    values_callable=_enum_values,
)
exercise_media_type_enum = Enum(
    ExerciseMediaType,
    name="exercise_media_type_enum",
    values_callable=_enum_values,
)


class Tenant(Base):
    """A studio or coaching business operating inside the platform."""

    __tablename__ = "tenants"

    tenant_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    slug = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    settings = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="ck_tenants_name_not_blank"),
        CheckConstraint("slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'", name="ck_tenants_slug_format"),
    )


class User(Base):
    """Platform identity shared across one or more tenants."""

    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    email = Column(String(320), nullable=False, unique=True, index=True)
    full_name = Column(String(255), nullable=False)
    password_hash = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    profile = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("position('@' in email) > 1", name="ck_users_email_basic"),
        CheckConstraint("btrim(full_name) <> ''", name="ck_users_full_name_not_blank"),
    )


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"

    tenant_membership_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(
        tenant_membership_role_enum,
        nullable=False,
        default=TenantMembershipRole.TRAINER.value,
        server_default=TenantMembershipRole.TRAINER.value,
    )
    status = Column(
        tenant_membership_status_enum,
        nullable=False,
        default=TenantMembershipStatus.ACTIVE.value,
        server_default=TenantMembershipStatus.ACTIVE.value,
    )
    invited_at = Column(DateTime(timezone=True), nullable=True)
    joined_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
        Index("ix_tenant_memberships_tenant_status", "tenant_id", "status"),
    )


class ClientProfile(Base):
    __tablename__ = "client_profiles"

    client_profile_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    primary_trainer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(client_status_enum, nullable=False, default=ClientStatus.ACTIVE.value, server_default=ClientStatus.ACTIVE.value)
    first_name = Column(String(120), nullable=False)
    last_name = Column(String(120), nullable=False)
    email = Column(String(320), nullable=True)
    phone = Column(String(32), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    intake_data = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("btrim(first_name) <> ''", name="ck_client_profiles_first_name_not_blank"),
        CheckConstraint("btrim(last_name) <> ''", name="ck_client_profiles_last_name_not_blank"),
        UniqueConstraint("tenant_id", "email", name="uq_client_profiles_tenant_email"),
        Index("ix_client_profiles_tenant_status", "tenant_id", "status"),
    )


class Exercise(Base):
    __tablename__ = "exercises"

    exercise_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(96), nullable=False)
    description = Column(Text, nullable=True)
    coaching_notes = Column(Text, nullable=True)
    tags = Column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    attributes = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    is_archived = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="ck_exercises_name_not_blank"),
        CheckConstraint("slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'", name="ck_exercises_slug_format"),
        UniqueConstraint("tenant_id", "slug", name="uq_exercises_tenant_slug"),
        Index("ix_exercises_tenant_archived", "tenant_id", "is_archived"),
    )


class ExerciseMedia(Base):
    __tablename__ = "exercise_media"

    exercise_media_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    exercise_id = Column(UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="CASCADE"), nullable=False, index=True)
    media_type = Column(exercise_media_type_enum, nullable=False)
    storage_url = Column(String, nullable=False)
    title = Column(String(255), nullable=True)
    sort_order = Column(Integer, nullable=False, default=1, server_default="1")
    is_primary = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("sort_order >= 1", name="ck_exercise_media_sort_order_positive"),
        UniqueConstraint("exercise_id", "sort_order", name="uq_exercise_media_exercise_sort_order"),
    )


class ProgramTemplate(Base):
    __tablename__ = "program_templates"

    program_template_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    goal = Column(Text, nullable=True)
    status = Column(
        program_template_status_enum,
        nullable=False,
        default=ProgramTemplateStatus.DRAFT.value,
        server_default=ProgramTemplateStatus.DRAFT.value,
    )
    version = Column(Integer, nullable=False, default=1, server_default="1")
    tags = Column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    metadata_json = Column(
        "metadata",
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="ck_program_templates_name_not_blank"),
        CheckConstraint("version >= 1", name="ck_program_templates_version_positive"),
        UniqueConstraint("tenant_id", "name", "version", name="uq_program_templates_tenant_name_version"),
        Index("ix_program_templates_tenant_status", "tenant_id", "status"),
    )


class ProgramTemplateWeek(Base):
    __tablename__ = "program_template_weeks"

    program_template_week_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    program_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("program_templates.program_template_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    week_number = Column(Integer, nullable=False)
    name = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("week_number >= 1", name="ck_program_template_weeks_week_number_positive"),
        UniqueConstraint("program_template_id", "week_number", name="uq_program_template_weeks_template_week"),
    )


class ProgramTemplateDay(Base):
    __tablename__ = "program_template_days"

    program_template_day_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    program_template_week_id = Column(
        UUID(as_uuid=True),
        ForeignKey("program_template_weeks.program_template_week_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_number = Column(Integer, nullable=False)
    name = Column(String(255), nullable=True)
    instructions = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("day_number >= 1", name="ck_program_template_days_day_number_positive"),
        UniqueConstraint("program_template_week_id", "day_number", name="uq_program_template_days_week_day"),
    )


class ProgramTemplateExercise(Base):
    __tablename__ = "program_template_exercises"

    program_template_exercise_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    program_template_day_id = Column(
        UUID(as_uuid=True),
        ForeignKey("program_template_days.program_template_day_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exercise_id = Column(UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="RESTRICT"), nullable=False, index=True)
    sort_order = Column(Integer, nullable=False)
    exercise_name_override = Column(String(255), nullable=True)
    sets_text = Column(String(64), nullable=True)
    reps_text = Column(String(64), nullable=True)
    load_text = Column(String(64), nullable=True)
    rest_text = Column(String(64), nullable=True)
    tempo_text = Column(String(64), nullable=True)
    rir_text = Column(String(64), nullable=True)
    duration_text = Column(String(64), nullable=True)
    distance_text = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    prescription = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("sort_order >= 1", name="ck_program_template_exercises_sort_order_positive"),
        UniqueConstraint("program_template_day_id", "sort_order", name="uq_program_template_exercises_day_sort"),
    )


class ClientProgram(Base):
    """Assigned client programs are cloned rows, not live-linked template projections."""

    __tablename__ = "client_programs"

    client_program_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    client_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("client_profiles.client_profile_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    source_program_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("program_templates.program_template_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    goal = Column(Text, nullable=True)
    status = Column(
        client_program_status_enum,
        nullable=False,
        default=ClientProgramStatus.DRAFT.value,
        server_default=ClientProgramStatus.DRAFT.value,
    )
    assigned_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    archived_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(
        "metadata",
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="ck_client_programs_name_not_blank"),
        Index("ix_client_programs_tenant_client_status", "tenant_id", "client_profile_id", "status"),
    )


class ClientProgramWeek(Base):
    __tablename__ = "client_program_weeks"

    client_program_week_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    client_program_id = Column(
        UUID(as_uuid=True),
        ForeignKey("client_programs.client_program_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    week_number = Column(Integer, nullable=False)
    name = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("week_number >= 1", name="ck_client_program_weeks_week_number_positive"),
        UniqueConstraint("client_program_id", "week_number", name="uq_client_program_weeks_program_week"),
    )


class ClientProgramDay(Base):
    __tablename__ = "client_program_days"

    client_program_day_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    client_program_week_id = Column(
        UUID(as_uuid=True),
        ForeignKey("client_program_weeks.client_program_week_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_number = Column(Integer, nullable=False)
    name = Column(String(255), nullable=True)
    instructions = Column(Text, nullable=True)
    status = Column(
        program_day_completion_status_enum,
        nullable=False,
        default=ProgramDayCompletionStatus.NOT_STARTED.value,
        server_default=ProgramDayCompletionStatus.NOT_STARTED.value,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("day_number >= 1", name="ck_client_program_days_day_number_positive"),
        UniqueConstraint("client_program_week_id", "day_number", name="uq_client_program_days_week_day"),
        Index("ix_client_program_days_tenant_status", "tenant_id", "status"),
    )


class ClientProgramExercise(Base):
    __tablename__ = "client_program_exercises"

    client_program_exercise_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    client_program_day_id = Column(
        UUID(as_uuid=True),
        ForeignKey("client_program_days.client_program_day_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_program_template_exercise_id = Column(
        UUID(as_uuid=True),
        ForeignKey("program_template_exercises.program_template_exercise_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    exercise_id = Column(UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="SET NULL"), nullable=True, index=True)
    sort_order = Column(Integer, nullable=False)
    exercise_name = Column(String(255), nullable=False)
    sets_text = Column(String(64), nullable=True)
    reps_text = Column(String(64), nullable=True)
    load_text = Column(String(64), nullable=True)
    rest_text = Column(String(64), nullable=True)
    tempo_text = Column(String(64), nullable=True)
    rir_text = Column(String(64), nullable=True)
    duration_text = Column(String(64), nullable=True)
    distance_text = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    prescription = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("sort_order >= 1", name="ck_client_program_exercises_sort_order_positive"),
        CheckConstraint("btrim(exercise_name) <> ''", name="ck_client_program_exercises_name_not_blank"),
        UniqueConstraint("client_program_day_id", "sort_order", name="uq_client_program_exercises_day_sort"),
    )


class WorkoutLog(Base):
    __tablename__ = "workout_logs"

    workout_log_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    client_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("client_profiles.client_profile_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_program_id = Column(UUID(as_uuid=True), ForeignKey("client_programs.client_program_id", ondelete="SET NULL"), nullable=True, index=True)
    client_program_day_id = Column(
        UUID(as_uuid=True),
        ForeignKey("client_program_days.client_program_day_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    logged_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    performed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    notes = Column(Text, nullable=True)
    summary = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_workout_logs_tenant_client_performed", "tenant_id", "client_profile_id", "performed_at"),
    )


class WorkoutLogExercise(Base):
    __tablename__ = "workout_log_exercises"

    workout_log_exercise_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    workout_log_id = Column(UUID(as_uuid=True), ForeignKey("workout_logs.workout_log_id", ondelete="CASCADE"), nullable=False, index=True)
    client_program_exercise_id = Column(
        UUID(as_uuid=True),
        ForeignKey("client_program_exercises.client_program_exercise_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    exercise_id = Column(UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="SET NULL"), nullable=True, index=True)
    sort_order = Column(Integer, nullable=False)
    exercise_name = Column(String(255), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("sort_order >= 1", name="ck_workout_log_exercises_sort_order_positive"),
        CheckConstraint("btrim(exercise_name) <> ''", name="ck_workout_log_exercises_name_not_blank"),
        UniqueConstraint("workout_log_id", "sort_order", name="uq_workout_log_exercises_log_sort"),
    )


class WorkoutLogSet(Base):
    __tablename__ = "workout_log_sets"

    workout_log_set_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    workout_log_exercise_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workout_log_exercises.workout_log_exercise_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    set_number = Column(Integer, nullable=False)
    reps_text = Column(String(64), nullable=True)
    load_text = Column(String(64), nullable=True)
    duration_text = Column(String(64), nullable=True)
    distance_text = Column(String(64), nullable=True)
    effort_text = Column(String(64), nullable=True)
    completed = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("set_number >= 1", name="ck_workout_log_sets_set_number_positive"),
        UniqueConstraint("workout_log_exercise_id", "set_number", name="uq_workout_log_sets_exercise_set"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    audit_event_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    action = Column(String(100), nullable=False)
    payload = Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    __table_args__ = (
        CheckConstraint("btrim(entity_type) <> ''", name="ck_audit_events_entity_type_not_blank"),
        CheckConstraint("btrim(action) <> ''", name="ck_audit_events_action_not_blank"),
        Index("ix_audit_events_tenant_entity_occurred", "tenant_id", "entity_type", "entity_id", "occurred_at"),
    )

"""add payroll t4 submission attempt events

Revision ID: d2e3f4a5b6c7
Revises: c9d8e7f6a5b4
Create Date: 2026-03-15 20:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c9d8e7f6a5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_t4_submission_attempt_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("submission_job_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["submission_job_id"],
            ["payroll_t4_submission_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "submission_job_id",
            "attempt_number",
            "event_type",
            name="uq_payroll_t4_sub_attempt_events_job_attempt_type",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_payroll_t4_sub_attempt_events_attempt_number_min",
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'ATTEMPT_CREATED', "
            "'VALIDATION_COMPLETED', "
            "'QUEUED', "
            "'TRANSMISSION_RECORDED', "
            "'RESPONSE_ACCEPTED', "
            "'RESPONSE_REJECTED', "
            "'FAILURE_RECORDED', "
            "'RETRIED'"
            ")",
            name="ck_payroll_t4_sub_attempt_events_type_valid",
        ),
    )
    op.create_index(
        op.f("ix_payroll_t4_submission_attempt_events_company_id"),
        "payroll_t4_submission_attempt_events",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_t4_submission_attempt_events_submission_job_id"),
        "payroll_t4_submission_attempt_events",
        ["submission_job_id"],
        unique=False,
    )
    op.create_index(
        "ix_payroll_t4_sub_attempt_events_company_job_time",
        "payroll_t4_submission_attempt_events",
        ["company_id", "submission_job_id", "event_timestamp"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO payroll_t4_submission_attempt_events (
            company_id,
            submission_job_id,
            attempt_number,
            event_type,
            event_timestamp,
            actor_user_id,
            payload_json
        )
        SELECT
            attempt.company_id,
            attempt.submission_job_id,
            attempt.attempt_number,
            'ATTEMPT_CREATED',
            attempt.created_at,
            job.created_by_user_id,
            jsonb_build_object(
                'submission_job_id', attempt.submission_job_id,
                'attempt_number', attempt.attempt_number,
                'status', job.status,
                'actor_user_id', job.created_by_user_id
            )
        FROM payroll_t4_submission_attempts AS attempt
        JOIN payroll_t4_submission_jobs AS job
          ON job.id = attempt.submission_job_id
        """
    )

    op.execute(
        """
        INSERT INTO payroll_t4_submission_attempt_events (
            company_id,
            submission_job_id,
            attempt_number,
            event_type,
            event_timestamp,
            actor_user_id,
            payload_json
        )
        SELECT
            attempt.company_id,
            attempt.submission_job_id,
            attempt.attempt_number,
            'VALIDATION_COMPLETED',
            CASE
                WHEN attempt.validated_at < attempt.created_at THEN attempt.created_at
                ELSE attempt.validated_at
            END,
            job.created_by_user_id,
            jsonb_build_object(
                'submission_job_id', attempt.submission_job_id,
                'attempt_number', attempt.attempt_number,
                'status', job.status,
                'actor_user_id', job.created_by_user_id,
                'validation_passed', attempt.validation_passed,
                'validated_at', to_jsonb(attempt.validated_at)
            )
        FROM payroll_t4_submission_attempts AS attempt
        JOIN payroll_t4_submission_jobs AS job
          ON job.id = attempt.submission_job_id
        WHERE attempt.validated_at IS NOT NULL
        """
    )

    op.execute(
        """
        INSERT INTO payroll_t4_submission_attempt_events (
            company_id,
            submission_job_id,
            attempt_number,
            event_type,
            event_timestamp,
            actor_user_id,
            payload_json
        )
        SELECT
            attempt.company_id,
            attempt.submission_job_id,
            attempt.attempt_number,
            'QUEUED',
            attempt.queued_at,
            NULL,
            jsonb_build_object(
                'submission_job_id', attempt.submission_job_id,
                'attempt_number', attempt.attempt_number,
                'status', job.status,
                'queued_at', to_jsonb(attempt.queued_at)
            )
        FROM payroll_t4_submission_attempts AS attempt
        JOIN payroll_t4_submission_jobs AS job
          ON job.id = attempt.submission_job_id
        WHERE attempt.queued_at IS NOT NULL
        """
    )

    op.execute(
        """
        INSERT INTO payroll_t4_submission_attempt_events (
            company_id,
            submission_job_id,
            attempt_number,
            event_type,
            event_timestamp,
            actor_user_id,
            payload_json
        )
        SELECT
            attempt.company_id,
            attempt.submission_job_id,
            attempt.attempt_number,
            'TRANSMISSION_RECORDED',
            attempt.transmission_recorded_at,
            transmission_event.actor_user_id,
            jsonb_build_object(
                'submission_job_id', attempt.submission_job_id,
                'attempt_number', attempt.attempt_number,
                'status', job.status,
                'actor_user_id', transmission_event.actor_user_id,
                'transmission_reference', job.transmission_reference,
                'transmission_recorded_at', to_jsonb(attempt.transmission_recorded_at)
            )
        FROM payroll_t4_submission_attempts AS attempt
        JOIN payroll_t4_submission_jobs AS job
          ON job.id = attempt.submission_job_id
        LEFT JOIN payroll_run_audit_events AS transmission_event
          ON transmission_event.company_id = attempt.company_id
         AND transmission_event.event_type = 'payroll_t4_submission_job_manual_transmission_recorded'
         AND transmission_event.payload_json ->> 'submission_job_id' = attempt.submission_job_id::text
        WHERE attempt.transmission_recorded_at IS NOT NULL
        """
    )

    op.execute(
        """
        INSERT INTO payroll_t4_submission_attempt_events (
            company_id,
            submission_job_id,
            attempt_number,
            event_type,
            event_timestamp,
            actor_user_id,
            payload_json
        )
        SELECT
            attempt.company_id,
            attempt.submission_job_id,
            attempt.attempt_number,
            CASE WHEN attempt.response_outcome = 'ACCEPTED' THEN 'RESPONSE_ACCEPTED' ELSE 'RESPONSE_REJECTED' END,
            attempt.response_recorded_at,
            response_event.actor_user_id,
            jsonb_build_object(
                'submission_job_id', attempt.submission_job_id,
                'attempt_number', attempt.attempt_number,
                'status', job.status,
                'actor_user_id', response_event.actor_user_id,
                'response_status', job.response_status,
                'response_reference', job.response_reference,
                'response_code', job.response_code,
                'response_message', job.response_message,
                'response_recorded_at', to_jsonb(attempt.response_recorded_at)
            )
        FROM payroll_t4_submission_attempts AS attempt
        JOIN payroll_t4_submission_jobs AS job
          ON job.id = attempt.submission_job_id
        LEFT JOIN payroll_run_audit_events AS response_event
          ON response_event.company_id = attempt.company_id
         AND response_event.event_type IN (
             'payroll_t4_submission_job_manual_response_accepted',
             'payroll_t4_submission_job_manual_response_rejected'
         )
         AND response_event.payload_json ->> 'submission_job_id' = attempt.submission_job_id::text
        WHERE attempt.response_recorded_at IS NOT NULL
          AND attempt.response_outcome IN ('ACCEPTED', 'REJECTED')
        """
    )

    op.execute(
        """
        INSERT INTO payroll_t4_submission_attempt_events (
            company_id,
            submission_job_id,
            attempt_number,
            event_type,
            event_timestamp,
            actor_user_id,
            payload_json
        )
        SELECT
            attempt.company_id,
            attempt.submission_job_id,
            attempt.attempt_number,
            'FAILURE_RECORDED',
            attempt.failure_recorded_at,
            failure_event.actor_user_id,
            jsonb_build_object(
                'submission_job_id', attempt.submission_job_id,
                'attempt_number', attempt.attempt_number,
                'status', job.status,
                'actor_user_id', failure_event.actor_user_id,
                'failure_code', job.failure_code,
                'failure_message', job.failure_message,
                'failure_reason', attempt.failure_reason,
                'failure_recorded_at', to_jsonb(attempt.failure_recorded_at)
            )
        FROM payroll_t4_submission_attempts AS attempt
        JOIN payroll_t4_submission_jobs AS job
          ON job.id = attempt.submission_job_id
        LEFT JOIN payroll_run_audit_events AS failure_event
          ON failure_event.company_id = attempt.company_id
         AND failure_event.event_type = 'payroll_t4_submission_job_manual_failure_recorded'
         AND failure_event.payload_json ->> 'submission_job_id' = attempt.submission_job_id::text
        WHERE attempt.failure_recorded_at IS NOT NULL
          AND attempt.response_outcome = 'FAILED_MANUAL'
        """
    )

    op.execute(
        """
        INSERT INTO payroll_t4_submission_attempt_events (
            company_id,
            submission_job_id,
            attempt_number,
            event_type,
            event_timestamp,
            actor_user_id,
            payload_json
        )
        SELECT
            audit.company_id,
            (audit.payload_json ->> 'submission_job_id')::integer,
            (audit.payload_json ->> 'prior_attempt_number')::integer,
            'RETRIED',
            audit.event_timestamp,
            audit.actor_user_id,
            jsonb_build_object(
                'submission_job_id', (audit.payload_json ->> 'submission_job_id')::integer,
                'attempt_number', (audit.payload_json ->> 'prior_attempt_number')::integer,
                'retried_to_attempt_number', (audit.payload_json ->> 'attempt_number')::integer,
                'status', COALESCE(audit.payload_json ->> 'status', 'PREPARED'),
                'actor_user_id', audit.actor_user_id
            )
        FROM payroll_run_audit_events AS audit
        WHERE audit.event_type = 'payroll_t4_submission_job_retried'
          AND NULLIF(audit.payload_json ->> 'submission_job_id', '') IS NOT NULL
          AND NULLIF(audit.payload_json ->> 'prior_attempt_number', '') IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_t4_sub_attempt_events_company_job_time", table_name="payroll_t4_submission_attempt_events")
    op.drop_index(op.f("ix_payroll_t4_submission_attempt_events_submission_job_id"), table_name="payroll_t4_submission_attempt_events")
    op.drop_index(op.f("ix_payroll_t4_submission_attempt_events_company_id"), table_name="payroll_t4_submission_attempt_events")
    op.drop_table("payroll_t4_submission_attempt_events")

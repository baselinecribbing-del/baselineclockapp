from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class PayrollT4SubmissionAttempt(Base):
    __tablename__ = "payroll_t4_submission_attempts"

    __table_args__ = (
        UniqueConstraint(
            "submission_job_id",
            "attempt_number",
            name="uq_payroll_t4_submission_attempts_job_attempt",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_payroll_t4_submission_attempts_attempt_number_min",
        ),
        CheckConstraint(
            "lifecycle_state IN ("
            "'CREATED', "
            "'VALIDATED', "
            "'QUEUED', "
            "'TRANSMISSION_RECORDED', "
            "'RESPONSE_ACCEPTED', "
            "'RESPONSE_REJECTED', "
            "'FAILURE_RECORDED'"
            ")",
            name="ck_payroll_t4_submission_attempts_lifecycle_state_valid",
        ),
        CheckConstraint(
            "response_outcome IS NULL OR response_outcome IN ('ACCEPTED', 'REJECTED', 'FAILED_MANUAL')",
            name="ck_payroll_t4_submission_attempts_response_outcome_valid",
        ),
        CheckConstraint(
            "(response_outcome <> 'FAILED_MANUAL') OR (NULLIF(btrim(COALESCE(failure_reason, '')), '') IS NOT NULL)",
            name="ck_payroll_t4_submission_attempts_failed_reason_required",
        ),
        CheckConstraint(
            "("
            "lifecycle_state = 'CREATED' "
            "AND validated_at IS NULL AND queued_at IS NULL "
            "AND transmission_recorded_at IS NULL AND response_recorded_at IS NULL "
            "AND failure_recorded_at IS NULL AND response_outcome IS NULL AND failure_reason IS NULL"
            ") OR ("
            "lifecycle_state = 'VALIDATED' "
            "AND validated_at IS NOT NULL AND queued_at IS NULL "
            "AND transmission_recorded_at IS NULL AND response_recorded_at IS NULL "
            "AND failure_recorded_at IS NULL AND response_outcome IS NULL AND failure_reason IS NULL"
            ") OR ("
            "lifecycle_state = 'QUEUED' "
            "AND validated_at IS NOT NULL AND queued_at IS NOT NULL "
            "AND transmission_recorded_at IS NULL AND response_recorded_at IS NULL "
            "AND failure_recorded_at IS NULL AND response_outcome IS NULL AND failure_reason IS NULL"
            ") OR ("
            "lifecycle_state = 'TRANSMISSION_RECORDED' "
            "AND validated_at IS NOT NULL AND queued_at IS NOT NULL "
            "AND transmission_recorded_at IS NOT NULL AND response_recorded_at IS NULL "
            "AND failure_recorded_at IS NULL AND response_outcome IS NULL AND failure_reason IS NULL"
            ") OR ("
            "lifecycle_state = 'RESPONSE_ACCEPTED' "
            "AND validated_at IS NOT NULL AND queued_at IS NOT NULL "
            "AND transmission_recorded_at IS NOT NULL AND response_recorded_at IS NOT NULL "
            "AND failure_recorded_at IS NULL AND response_outcome = 'ACCEPTED' AND failure_reason IS NULL"
            ") OR ("
            "lifecycle_state = 'RESPONSE_REJECTED' "
            "AND validated_at IS NOT NULL AND queued_at IS NOT NULL "
            "AND transmission_recorded_at IS NOT NULL AND response_recorded_at IS NOT NULL "
            "AND failure_recorded_at IS NULL AND response_outcome = 'REJECTED' AND failure_reason IS NULL"
            ") OR ("
            "lifecycle_state = 'FAILURE_RECORDED' "
            "AND validated_at IS NOT NULL "
            "AND failure_recorded_at IS NOT NULL "
            "AND response_recorded_at IS NULL "
            "AND response_outcome = 'FAILED_MANUAL' "
            "AND NULLIF(btrim(COALESCE(failure_reason, '')), '') IS NOT NULL"
            ")",
            name="ck_payroll_t4_sub_attempts_lifecycle_fields_complete",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    submission_job_id = Column(
        Integer,
        ForeignKey("payroll_t4_submission_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempt_number = Column(Integer, nullable=False)
    lifecycle_state = Column(String, nullable=False, server_default="CREATED")
    validation_passed = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    validated_at = Column(DateTime(timezone=True), nullable=True)
    queued_at = Column(DateTime(timezone=True), nullable=True)
    transmission_recorded_at = Column(DateTime(timezone=True), nullable=True)
    response_recorded_at = Column(DateTime(timezone=True), nullable=True)
    failure_recorded_at = Column(DateTime(timezone=True), nullable=True)
    response_outcome = Column(String, nullable=True)
    failure_reason = Column(String, nullable=True)

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import Index

from app.database import Base


class PayrollT4SubmissionAttemptEvent(Base):
    __tablename__ = "payroll_t4_submission_attempt_events"

    __table_args__ = (
        UniqueConstraint(
            "submission_job_id",
            "attempt_number",
            "event_type",
            name="uq_payroll_t4_sub_attempt_events_job_attempt_type",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_payroll_t4_sub_attempt_events_attempt_number_min",
        ),
        CheckConstraint(
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
        Index(
            "ix_payroll_t4_sub_attempt_events_company_job_time",
            "company_id",
            "submission_job_id",
            "event_timestamp",
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
    event_type = Column(String, nullable=False)
    event_timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_user_id = Column(String, nullable=True)
    payload_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

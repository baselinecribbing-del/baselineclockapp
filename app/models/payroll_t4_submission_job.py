from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class PayrollT4SubmissionJob(Base):
    __tablename__ = "payroll_t4_submission_jobs"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "tax_year",
            "xml_package_sha256",
            name="uq_payroll_t4_submission_jobs_company_year_xml_hash",
        ),
        CheckConstraint("tax_year >= 2000", name="ck_payroll_t4_submission_jobs_tax_year_min"),
        CheckConstraint(
            "status IN ('PREPARED', 'TRANSMISSION_RECORDED_MANUAL', 'FAILED_MANUAL', 'RESPONSE_ACCEPTED_MANUAL', 'RESPONSE_REJECTED_MANUAL')",
            name="ck_payroll_t4_submission_jobs_status_valid",
        ),
        CheckConstraint(
            "("
            "status = 'PREPARED' AND transmission_started_at IS NULL "
            "AND transmission_completed_at IS NULL AND transmission_reference IS NULL "
            "AND response_status IS NULL AND response_recorded_at IS NULL "
            "AND response_recorded_by_user_id IS NULL AND response_reference IS NULL "
            "AND response_code IS NULL AND response_message IS NULL "
            "AND failure_code IS NULL AND failure_message IS NULL"
            ") OR ("
            "status = 'TRANSMISSION_RECORDED_MANUAL' AND transmission_started_at IS NOT NULL "
            "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
            "AND transmission_completed_at >= transmission_started_at "
            "AND response_status IS NULL AND response_recorded_at IS NULL "
            "AND response_recorded_by_user_id IS NULL AND response_reference IS NULL "
            "AND response_code IS NULL AND response_message IS NULL "
            "AND failure_code IS NULL AND failure_message IS NULL"
            ") OR ("
            "status = 'FAILED_MANUAL' AND response_status IS NULL "
            "AND response_recorded_at IS NULL AND response_recorded_by_user_id IS NULL "
            "AND response_reference IS NULL AND response_code IS NULL AND response_message IS NULL "
            "AND (NULLIF(btrim(COALESCE(failure_code, '')), '') IS NOT NULL "
            "OR NULLIF(btrim(COALESCE(failure_message, '')), '') IS NOT NULL)"
            ") OR ("
            "status = 'RESPONSE_ACCEPTED_MANUAL' AND transmission_started_at IS NOT NULL "
            "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
            "AND transmission_completed_at >= transmission_started_at "
            "AND response_status = 'ACCEPTED' AND response_recorded_at IS NOT NULL "
            "AND failure_code IS NULL AND failure_message IS NULL"
            ") OR ("
            "status = 'RESPONSE_REJECTED_MANUAL' AND transmission_started_at IS NOT NULL "
            "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
            "AND transmission_completed_at >= transmission_started_at "
            "AND response_status = 'REJECTED' AND response_recorded_at IS NOT NULL "
            "AND failure_code IS NULL AND failure_message IS NULL "
            "AND (NULLIF(btrim(COALESCE(response_code, '')), '') IS NOT NULL "
            "OR NULLIF(btrim(COALESCE(response_message, '')), '') IS NOT NULL)"
            ")",
            name="ck_payroll_t4_submission_jobs_manual_record_complete",
        ),
        CheckConstraint(
            "response_status IS NULL OR response_status IN ('ACCEPTED', 'REJECTED')",
            name="ck_payroll_t4_submission_jobs_response_status_valid",
        ),
        CheckConstraint(
            "validation_mode IN ('INTERNAL_ONLY')",
            name="ck_payroll_t4_submission_jobs_validation_mode_valid",
        ),
        CheckConstraint(
            "validation_status IN ('VALID')",
            name="ck_payroll_t4_submission_jobs_validation_status_valid",
        ),
        CheckConstraint(
            "final_outcome IS NULL OR final_outcome IN ('ACCEPTED', 'REJECTED', 'FAILED_MANUAL')",
            name="ck_payroll_t4_submission_jobs_final_outcome_valid",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    tax_year = Column(Integer, nullable=False, index=True)
    filing_artifact_id = Column(
        String,
        ForeignKey("payroll_t4_filing_artifacts.filing_artifact_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by_user_id = Column(String, nullable=True)
    queued_at = Column(DateTime(timezone=True), nullable=True)
    transmission_started_at = Column(DateTime(timezone=True), nullable=True)
    transmission_completed_at = Column(DateTime(timezone=True), nullable=True)
    transmission_reference = Column(String, nullable=True)
    response_status = Column(String, nullable=True)
    response_recorded_at = Column(DateTime(timezone=True), nullable=True)
    response_recorded_by_user_id = Column(String, nullable=True)
    response_reference = Column(String, nullable=True)
    response_code = Column(String, nullable=True)
    response_message = Column(String, nullable=True)
    failure_code = Column(String, nullable=True)
    failure_message = Column(String, nullable=True)
    final_outcome = Column(String, nullable=True)
    final_outcome_detail = Column(String, nullable=True)
    filing_artifact_sha256 = Column(String, nullable=False)
    xml_package_sha256 = Column(String, nullable=False)
    validation_validator_id = Column(String, nullable=False)
    validation_validator_version = Column(String, nullable=False)
    validation_mode = Column(String, nullable=False)
    validation_status = Column(String, nullable=False)
    validated_at = Column(DateTime(timezone=True), nullable=False)
    validated_by_user_id = Column(String, nullable=True)

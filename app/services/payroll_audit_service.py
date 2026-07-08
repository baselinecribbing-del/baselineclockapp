from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.payroll_run_audit_event import PayrollRunAuditEvent

PAYROLL_RUN_CREATED_EVENT = "payroll_run_created"
PAYROLL_RUN_EXECUTED_EVENT = "payroll_run_executed"
PAYROLL_RUN_FINALIZED_EVENT = "payroll_run_finalized"
PAYROLL_RUN_MARKED_SUPERSEDED_EVENT = "payroll_run_marked_superseded"
PAYROLL_REMITTANCE_OBLIGATION_PREPARED_EVENT = "payroll_remittance_obligation_prepared"
PAYROLL_REMITTANCE_MARKED_REMITTED_MANUAL_EVENT = "payroll_remittance_marked_remitted_manual"
PAYROLL_REMITTANCE_REFERENCE_RECORDED_EVENT = "payroll_remittance_reference_recorded"
PAYROLL_REMITTANCE_PAYMENT_RECORDED_EVENT = "payroll_remittance_payment_recorded"
PAYROLL_T4_EXPORT_PREPARED_EVENT = "payroll_t4_export_prepared"
PAYROLL_T4_FILING_ARTIFACT_PREPARED_EVENT = "payroll_t4_filing_artifact_prepared"
PAYROLL_T4_XML_PACKAGE_GENERATED_EVENT = "payroll_t4_xml_package_generated"
PAYROLL_T4_XML_PACKAGE_REGENERATED_EVENT = "payroll_t4_xml_package_regenerated"
PAYROLL_T4_XML_VALIDATION_PASSED_EVENT = "payroll_t4_xml_validation_passed"
PAYROLL_T4_XML_VALIDATION_FAILED_EVENT = "payroll_t4_xml_validation_failed"
PAYROLL_T4_SUBMISSION_JOB_CREATED_EVENT = "payroll_t4_submission_job_created"
PAYROLL_T4_SUBMISSION_JOB_QUEUED_EVENT = "payroll_t4_submission_job_queued"
PAYROLL_T4_SUBMISSION_JOB_MANUAL_TRANSMISSION_RECORDED_EVENT = "payroll_t4_submission_job_manual_transmission_recorded"
PAYROLL_T4_SUBMISSION_JOB_MANUAL_FAILURE_RECORDED_EVENT = "payroll_t4_submission_job_manual_failure_recorded"
PAYROLL_T4_SUBMISSION_JOB_MANUAL_RESPONSE_ACCEPTED_EVENT = "payroll_t4_submission_job_manual_response_accepted"
PAYROLL_T4_SUBMISSION_JOB_MANUAL_RESPONSE_REJECTED_EVENT = "payroll_t4_submission_job_manual_response_rejected"
PAYROLL_T4_SUBMISSION_JOB_RETRIED_EVENT = "payroll_t4_submission_job_retried"
PAYROLL_T4_MARKED_DELIVERED_MANUAL_EVENT = "payroll_t4_marked_delivered_manual"
PAYROLL_T4_ACKNOWLEDGED_BY_EMPLOYEE_EVENT = "payroll_t4_acknowledged_by_employee"


def record_payroll_audit_event(
    *,
    db: Session,
    company_id: int,
    event_type: str,
    actor_user_id: str | None,
    payload_json: dict[str, Any] | None = None,
    payroll_run_id: str | None = None,
) -> PayrollRunAuditEvent:
    row = PayrollRunAuditEvent(
        company_id=int(company_id),
        payroll_run_id=None if payroll_run_id is None else str(payroll_run_id),
        event_type=str(event_type),
        actor_user_id=None if actor_user_id is None else str(actor_user_id),
        payload_json=dict(payload_json or {}),
    )
    db.add(row)
    db.flush()
    return row

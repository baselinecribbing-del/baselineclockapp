from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.event_outbox import EventOutbox
from app.models.payroll_t4_filing_artifact import PayrollT4FilingArtifact
from app.models.payroll_t4_submission_attempt import PayrollT4SubmissionAttempt
from app.models.payroll_t4_submission_attempt_event import PayrollT4SubmissionAttemptEvent
from app.models.payroll_t4_submission_job import PayrollT4SubmissionJob
from app.services.payroll_audit_service import (
    PAYROLL_T4_SUBMISSION_JOB_CREATED_EVENT,
    PAYROLL_T4_SUBMISSION_JOB_RETRIED_EVENT,
    PAYROLL_T4_SUBMISSION_JOB_QUEUED_EVENT,
    PAYROLL_T4_SUBMISSION_JOB_MANUAL_FAILURE_RECORDED_EVENT,
    PAYROLL_T4_SUBMISSION_JOB_MANUAL_RESPONSE_ACCEPTED_EVENT,
    PAYROLL_T4_SUBMISSION_JOB_MANUAL_RESPONSE_REJECTED_EVENT,
    PAYROLL_T4_SUBMISSION_JOB_MANUAL_TRANSMISSION_RECORDED_EVENT,
    record_payroll_audit_event,
)
from app.services.payroll_t4_filing_artifact_service import get_payroll_t4_filing_artifact_row
from app.services.payroll_t4_xml_validation_service import (
    get_active_payroll_t4_xml_validator,
)


@dataclass(frozen=True)
class PayrollT4SubmissionJobRecord:
    id: int
    company_id: int
    tax_year: int
    filing_artifact_id: str
    status: str
    created_at: datetime
    created_by_user_id: str | None
    queued_at: datetime | None
    transmission_started_at: datetime | None
    transmission_completed_at: datetime | None
    transmission_reference: str | None
    response_status: str | None
    response_recorded_at: datetime | None
    response_recorded_by_user_id: str | None
    response_reference: str | None
    response_code: str | None
    response_message: str | None
    failure_code: str | None
    failure_message: str | None
    final_outcome: str | None
    final_outcome_detail: str | None
    xml_package_sha256: str
    filing_artifact_sha256: str
    validation_validator_id: str
    validation_validator_version: str
    validation_mode: str
    validation_status: str
    validated_at: datetime
    validated_by_user_id: str | None


@dataclass(frozen=True)
class PayrollT4SubmissionAttemptRecord:
    id: int
    company_id: int
    submission_job_id: int
    attempt_number: int
    lifecycle_state: str
    validation_passed: bool
    created_at: datetime
    validated_at: datetime | None
    queued_at: datetime | None
    transmission_recorded_at: datetime | None
    response_recorded_at: datetime | None
    failure_recorded_at: datetime | None
    response_outcome: str | None
    failure_reason: str | None


@dataclass(frozen=True)
class PayrollT4SubmissionAttemptEventRecord:
    id: int
    company_id: int
    submission_job_id: int
    attempt_number: int
    event_type: str
    event_timestamp: datetime
    actor_user_id: str | None
    payload_json: dict[str, Any]


def _normalize_manual_reference(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_manual_response_status(value: str | None) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized == "":
        return None
    if normalized not in {"ACCEPTED", "REJECTED"}:
        raise ValueError("response_status must be ACCEPTED or REJECTED")
    return normalized


def _serialize_utc_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def _normalize_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_optional_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _normalize_utc_datetime(value)


def _normalize_snapshot_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_snapshot_upper_text(value: str | None) -> str | None:
    normalized = _normalize_snapshot_text(value)
    if normalized is None:
        return None
    return normalized.upper()


def _normalize_attempt_event_type(value: str | None) -> str | None:
    normalized = _normalize_snapshot_upper_text(value)
    if normalized is None:
        return None
    allowed = {
        "ATTEMPT_CREATED",
        "VALIDATION_COMPLETED",
        "QUEUED",
        "TRANSMISSION_RECORDED",
        "RESPONSE_ACCEPTED",
        "RESPONSE_REJECTED",
        "FAILURE_RECORDED",
        "RETRIED",
    }
    if normalized not in allowed:
        raise ValueError("Unsupported submission attempt event type")
    return normalized


def _normalize_iso8601_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _serialize_utc_timestamp(value)

    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _normalize_queued_submission_job_payload(payload: dict | None) -> dict:
    raw = dict(payload or {})
    normalized = dict(raw)
    normalized["submission_job_id"] = int(raw["submission_job_id"]) if raw.get("submission_job_id") is not None else None
    normalized["company_id"] = int(raw["company_id"]) if raw.get("company_id") is not None else None
    normalized["status"] = _normalize_snapshot_upper_text(raw.get("status"))
    normalized["tax_year"] = int(raw["tax_year"]) if raw.get("tax_year") is not None else None
    normalized["filing_artifact_id"] = _normalize_snapshot_text(raw.get("filing_artifact_id"))
    normalized["xml_package_sha256"] = _normalize_snapshot_text(raw.get("xml_package_sha256"))
    normalized["artifact_sha256"] = _normalize_snapshot_text(raw.get("artifact_sha256"))
    normalized["validation_validator_id"] = _normalize_snapshot_text(raw.get("validation_validator_id"))
    normalized["validation_validator_version"] = _normalize_snapshot_text(raw.get("validation_validator_version"))
    normalized["validation_mode"] = _normalize_snapshot_upper_text(raw.get("validation_mode"))
    normalized["validation_status"] = _normalize_snapshot_upper_text(raw.get("validation_status"))
    normalized["validated_at"] = _normalize_iso8601_timestamp(raw.get("validated_at"))
    normalized["validated_by_user_id"] = _normalize_snapshot_text(raw.get("validated_by_user_id"))
    normalized["queued_at"] = _normalize_iso8601_timestamp(raw.get("queued_at"))
    return normalized


def _build_canonical_validation_snapshot_payload(row: PayrollT4SubmissionJob) -> dict[str, str | None]:
    return {
        "artifact_sha256": _normalize_snapshot_text(row.filing_artifact_sha256),
        "xml_hash": _normalize_snapshot_text(row.xml_package_sha256),
        "xml_package_sha256": _normalize_snapshot_text(row.xml_package_sha256),
        "validation_validator_id": _normalize_snapshot_text(row.validation_validator_id),
        "validation_validator_version": _normalize_snapshot_text(row.validation_validator_version),
        "validation_mode": _normalize_snapshot_upper_text(row.validation_mode),
        "validation_status": _normalize_snapshot_upper_text(row.validation_status),
        "validated_at": _serialize_utc_timestamp(row.validated_at),
        "validated_by_user_id": _normalize_snapshot_text(row.validated_by_user_id),
    }


def _build_attempt_failure_reason(*, failure_code: str | None, failure_message: str | None) -> str | None:
    normalized_code = _normalize_snapshot_text(failure_code)
    normalized_message = _normalize_snapshot_text(failure_message)
    if normalized_code and normalized_message:
        return f"{normalized_code}: {normalized_message}"
    return normalized_code or normalized_message


def _derive_attempt_response_outcome(row: PayrollT4SubmissionJob) -> str | None:
    status = str(row.status)
    if status == "RESPONSE_ACCEPTED_MANUAL":
        return "ACCEPTED"
    if status == "RESPONSE_REJECTED_MANUAL":
        return "REJECTED"
    if status == "FAILED_MANUAL":
        return "FAILED_MANUAL"
    return None


def _derive_submission_job_final_outcome(row: PayrollT4SubmissionJob) -> str | None:
    status = str(row.status)
    if status == "RESPONSE_ACCEPTED_MANUAL":
        return "ACCEPTED"
    if status == "RESPONSE_REJECTED_MANUAL":
        return "REJECTED"
    if status == "FAILED_MANUAL":
        return "FAILED_MANUAL"
    return None


def _derive_submission_job_final_outcome_detail(row: PayrollT4SubmissionJob) -> str | None:
    outcome = _derive_submission_job_final_outcome(row)
    if outcome == "ACCEPTED":
        return _normalize_snapshot_text(row.response_message) or _normalize_snapshot_text(row.response_reference)
    if outcome == "REJECTED":
        return (
            _normalize_snapshot_text(row.response_message)
            or _normalize_snapshot_text(row.response_code)
            or _normalize_snapshot_text(row.response_reference)
        )
    if outcome == "FAILED_MANUAL":
        return _normalize_snapshot_text(row.failure_message) or _normalize_snapshot_text(row.failure_code)
    return None


def _derive_attempt_lifecycle_state(row: PayrollT4SubmissionJob) -> str:
    status = str(row.status)
    if status == "RESPONSE_ACCEPTED_MANUAL":
        return "RESPONSE_ACCEPTED"
    if status == "RESPONSE_REJECTED_MANUAL":
        return "RESPONSE_REJECTED"
    if status == "FAILED_MANUAL":
        return "FAILURE_RECORDED"
    if row.transmission_completed_at is not None:
        return "TRANSMISSION_RECORDED"
    if row.queued_at is not None:
        return "QUEUED"
    if str(row.validation_status) == "VALID":
        return "VALIDATED"
    return "CREATED"


def _derive_attempt_queued_at(row: PayrollT4SubmissionJob) -> datetime | None:
    queued_at = _normalize_optional_utc_datetime(row.queued_at)
    if queued_at is not None:
        return queued_at
    if row.transmission_completed_at is not None:
        return _normalize_utc_datetime(row.transmission_completed_at)
    if row.response_recorded_at is not None:
        return _normalize_utc_datetime(row.response_recorded_at)
    return None


def _derive_attempt_failure_recorded_at(row: PayrollT4SubmissionJob) -> datetime | None:
    if str(row.status) != "FAILED_MANUAL":
        return None
    if row.transmission_completed_at is not None:
        return _normalize_utc_datetime(row.transmission_completed_at)
    return _normalize_utc_datetime(row.created_at)


def _build_attempt_event_payload(
    *,
    row: PayrollT4SubmissionJob,
    attempt_number: int,
    event_type: str,
    actor_user_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "submission_job_id": int(row.id),
        "attempt_number": int(attempt_number),
        "status": str(row.status),
        "actor_user_id": _normalize_snapshot_text(actor_user_id),
    }
    if event_type == "VALIDATION_COMPLETED":
        payload["validation_passed"] = str(row.validation_status) == "VALID"
        payload["validated_at"] = _serialize_utc_timestamp(row.validated_at)
    elif event_type == "QUEUED":
        payload["queued_at"] = _serialize_utc_timestamp(_derive_attempt_queued_at(row))
    elif event_type == "TRANSMISSION_RECORDED":
        payload["transmission_reference"] = _normalize_snapshot_text(row.transmission_reference)
        payload["transmission_recorded_at"] = _serialize_utc_timestamp(
            _normalize_optional_utc_datetime(row.transmission_completed_at)
        )
    elif event_type in {"RESPONSE_ACCEPTED", "RESPONSE_REJECTED"}:
        payload["response_status"] = _normalize_snapshot_upper_text(row.response_status)
        payload["response_reference"] = _normalize_snapshot_text(row.response_reference)
        payload["response_code"] = _normalize_snapshot_text(row.response_code)
        payload["response_message"] = _normalize_snapshot_text(row.response_message)
        payload["response_recorded_at"] = _serialize_utc_timestamp(
            _normalize_optional_utc_datetime(row.response_recorded_at)
        )
    elif event_type == "FAILURE_RECORDED":
        payload["failure_code"] = _normalize_snapshot_text(row.failure_code)
        payload["failure_message"] = _normalize_snapshot_text(row.failure_message)
        payload["failure_reason"] = _build_attempt_failure_reason(
            failure_code=row.failure_code,
            failure_message=row.failure_message,
        )
        payload["failure_recorded_at"] = _serialize_utc_timestamp(_derive_attempt_failure_recorded_at(row))
    return payload


def _record_submission_attempt_event(
    *,
    db: Session,
    row: PayrollT4SubmissionJob,
    attempt_number: int,
    event_type: str,
    actor_user_id: str | None,
    event_timestamp: datetime,
    payload_json: dict[str, Any] | None = None,
) -> PayrollT4SubmissionAttemptEvent:
    normalized_event_type = str(_normalize_attempt_event_type(event_type))
    normalized_actor_user_id = _normalize_snapshot_text(actor_user_id)
    normalized_timestamp = _normalize_utc_datetime(event_timestamp)
    payload = dict(payload_json or {})
    existing = (
        db.query(PayrollT4SubmissionAttemptEvent)
        .filter(PayrollT4SubmissionAttemptEvent.company_id == int(row.company_id))
        .filter(PayrollT4SubmissionAttemptEvent.submission_job_id == int(row.id))
        .filter(PayrollT4SubmissionAttemptEvent.attempt_number == int(attempt_number))
        .filter(PayrollT4SubmissionAttemptEvent.event_type == normalized_event_type)
        .one_or_none()
    )
    if existing is not None:
        changed = False
        if existing.event_timestamp != normalized_timestamp:
            existing.event_timestamp = normalized_timestamp
            changed = True
        if _normalize_snapshot_text(existing.actor_user_id) != normalized_actor_user_id:
            existing.actor_user_id = normalized_actor_user_id
            changed = True
        if dict(existing.payload_json or {}) != payload:
            existing.payload_json = payload
            changed = True
        if changed:
            db.flush()
        return existing

    event = PayrollT4SubmissionAttemptEvent(
        company_id=int(row.company_id),
        submission_job_id=int(row.id),
        attempt_number=int(attempt_number),
        event_type=normalized_event_type,
        event_timestamp=normalized_timestamp,
        actor_user_id=normalized_actor_user_id,
        payload_json=payload,
    )
    db.add(event)
    db.flush()
    return event


def _record_attempt_created_and_validation_events(
    *,
    db: Session,
    row: PayrollT4SubmissionJob,
    attempt: PayrollT4SubmissionAttempt,
    actor_user_id: str | None,
) -> None:
    created_at = _normalize_utc_datetime(attempt.created_at)
    _record_submission_attempt_event(
        db=db,
        row=row,
        attempt_number=int(attempt.attempt_number),
        event_type="ATTEMPT_CREATED",
        actor_user_id=actor_user_id,
        event_timestamp=created_at,
        payload_json=_build_attempt_event_payload(
            row=row,
            attempt_number=int(attempt.attempt_number),
            event_type="ATTEMPT_CREATED",
            actor_user_id=actor_user_id,
        ),
    )
    if attempt.validated_at is not None:
        validated_at = _normalize_utc_datetime(attempt.validated_at)
        if validated_at < created_at:
            validated_at = created_at
        _record_submission_attempt_event(
            db=db,
            row=row,
            attempt_number=int(attempt.attempt_number),
            event_type="VALIDATION_COMPLETED",
            actor_user_id=actor_user_id,
            event_timestamp=validated_at,
            payload_json=_build_attempt_event_payload(
                row=row,
                attempt_number=int(attempt.attempt_number),
                event_type="VALIDATION_COMPLETED",
                actor_user_id=actor_user_id,
            ),
        )


def _get_latest_submission_attempt(
    *,
    db: Session,
    company_id: int,
    submission_job_id: int,
) -> PayrollT4SubmissionAttempt | None:
    return (
        db.query(PayrollT4SubmissionAttempt)
        .filter(PayrollT4SubmissionAttempt.company_id == int(company_id))
        .filter(PayrollT4SubmissionAttempt.submission_job_id == int(submission_job_id))
        .order_by(
            PayrollT4SubmissionAttempt.attempt_number.desc(),
            PayrollT4SubmissionAttempt.id.desc(),
        )
        .first()
    )


def _build_retry_attempt(
    *,
    db: Session,
    row: PayrollT4SubmissionJob,
) -> PayrollT4SubmissionAttempt:
    latest_attempt = _get_latest_submission_attempt(
        db=db,
        company_id=int(row.company_id),
        submission_job_id=int(row.id),
    )
    next_attempt_number = 1 if latest_attempt is None else int(latest_attempt.attempt_number) + 1
    created_at = datetime.now(timezone.utc)
    attempt = PayrollT4SubmissionAttempt(
        company_id=int(row.company_id),
        submission_job_id=int(row.id),
        attempt_number=next_attempt_number,
        lifecycle_state="VALIDATED",
        validation_passed=str(row.validation_status) == "VALID",
        created_at=created_at,
        validated_at=_normalize_utc_datetime(row.validated_at) if str(row.validation_status) == "VALID" else None,
    )
    db.add(attempt)
    db.flush()
    return attempt


def _sync_latest_submission_attempt_from_job(
    *,
    db: Session,
    row: PayrollT4SubmissionJob,
) -> PayrollT4SubmissionAttempt:
    attempt = _get_latest_submission_attempt(
        db=db,
        company_id=int(row.company_id),
        submission_job_id=int(row.id),
    )
    changed = False
    if attempt is None:
        attempt = PayrollT4SubmissionAttempt(
            company_id=int(row.company_id),
            submission_job_id=int(row.id),
            attempt_number=1,
            lifecycle_state="CREATED",
            validation_passed=str(row.validation_status) == "VALID",
            created_at=_normalize_utc_datetime(row.created_at),
        )
        db.add(attempt)
        db.flush()

    normalized_created_at = _normalize_utc_datetime(row.created_at)
    if attempt.created_at != normalized_created_at:
        attempt.created_at = normalized_created_at
        changed = True

    validation_passed = str(row.validation_status) == "VALID"
    if bool(attempt.validation_passed) != validation_passed:
        attempt.validation_passed = validation_passed
        changed = True

    normalized_validated_at = _normalize_optional_utc_datetime(row.validated_at) if validation_passed else None
    if attempt.validated_at != normalized_validated_at:
        attempt.validated_at = normalized_validated_at
        changed = True

    normalized_queued_at = _derive_attempt_queued_at(row)
    if attempt.queued_at != normalized_queued_at:
        attempt.queued_at = normalized_queued_at
        changed = True

    normalized_transmission_recorded_at = _normalize_optional_utc_datetime(row.transmission_completed_at)
    if attempt.transmission_recorded_at != normalized_transmission_recorded_at:
        attempt.transmission_recorded_at = normalized_transmission_recorded_at
        changed = True

    normalized_response_recorded_at = _normalize_optional_utc_datetime(row.response_recorded_at)
    if attempt.response_recorded_at != normalized_response_recorded_at:
        attempt.response_recorded_at = normalized_response_recorded_at
        changed = True

    derived_response_outcome = _derive_attempt_response_outcome(row)
    if _normalize_snapshot_upper_text(attempt.response_outcome) != derived_response_outcome:
        attempt.response_outcome = derived_response_outcome
        changed = True

    derived_failure_reason = _build_attempt_failure_reason(
        failure_code=row.failure_code,
        failure_message=row.failure_message,
    )
    if _normalize_snapshot_text(attempt.failure_reason) != derived_failure_reason:
        attempt.failure_reason = derived_failure_reason
        changed = True

    normalized_failure_recorded_at = _derive_attempt_failure_recorded_at(row)
    if attempt.failure_recorded_at != normalized_failure_recorded_at:
        attempt.failure_recorded_at = normalized_failure_recorded_at
        changed = True

    derived_lifecycle_state = _derive_attempt_lifecycle_state(row)
    if str(attempt.lifecycle_state) != derived_lifecycle_state:
        attempt.lifecycle_state = derived_lifecycle_state
        changed = True

    if changed:
        db.flush()
    return attempt


def _repair_submission_job_snapshot_fields(row: PayrollT4SubmissionJob) -> bool:
    changed = False

    normalized_created_by_user_id = _normalize_snapshot_text(row.created_by_user_id)
    if row.created_by_user_id != normalized_created_by_user_id:
        row.created_by_user_id = normalized_created_by_user_id
        changed = True

    normalized_filing_artifact_id = _normalize_snapshot_text(row.filing_artifact_id)
    if row.filing_artifact_id != normalized_filing_artifact_id:
        row.filing_artifact_id = normalized_filing_artifact_id
        changed = True

    normalized_filing_artifact_sha256 = _normalize_snapshot_text(row.filing_artifact_sha256)
    if row.filing_artifact_sha256 != normalized_filing_artifact_sha256:
        row.filing_artifact_sha256 = normalized_filing_artifact_sha256
        changed = True

    normalized_xml_package_sha256 = _normalize_snapshot_text(row.xml_package_sha256)
    if row.xml_package_sha256 != normalized_xml_package_sha256:
        row.xml_package_sha256 = normalized_xml_package_sha256
        changed = True

    normalized_validation_validator_id = _normalize_snapshot_text(row.validation_validator_id)
    if row.validation_validator_id != normalized_validation_validator_id:
        row.validation_validator_id = normalized_validation_validator_id
        changed = True

    normalized_validation_validator_version = _normalize_snapshot_text(row.validation_validator_version)
    if row.validation_validator_version != normalized_validation_validator_version:
        row.validation_validator_version = normalized_validation_validator_version
        changed = True

    normalized_validation_mode = _normalize_snapshot_upper_text(row.validation_mode)
    if row.validation_mode != normalized_validation_mode:
        row.validation_mode = normalized_validation_mode
        changed = True

    normalized_validation_status = _normalize_snapshot_upper_text(row.validation_status)
    if row.validation_status != normalized_validation_status:
        row.validation_status = normalized_validation_status
        changed = True

    normalized_validated_at = _normalize_utc_datetime(row.validated_at)
    if row.validated_at != normalized_validated_at:
        row.validated_at = normalized_validated_at
        changed = True

    normalized_validated_by_user_id = _normalize_snapshot_text(row.validated_by_user_id)
    if row.validated_by_user_id != normalized_validated_by_user_id:
        row.validated_by_user_id = normalized_validated_by_user_id
        changed = True

    derived_final_outcome = _derive_submission_job_final_outcome(row)
    if _normalize_snapshot_upper_text(row.final_outcome) != derived_final_outcome:
        row.final_outcome = derived_final_outcome
        changed = True

    derived_final_outcome_detail = _derive_submission_job_final_outcome_detail(row)
    if _normalize_snapshot_text(row.final_outcome_detail) != derived_final_outcome_detail:
        row.final_outcome_detail = derived_final_outcome_detail
        changed = True

    return changed


def _repair_manual_transmission_fields(row: PayrollT4SubmissionJob) -> bool:
    changed = _repair_submission_job_snapshot_fields(row)

    if row.transmission_started_at is not None:
        normalized_transmission_started_at = _normalize_utc_datetime(row.transmission_started_at)
        if row.transmission_started_at != normalized_transmission_started_at:
            row.transmission_started_at = normalized_transmission_started_at
            changed = True

    if row.transmission_completed_at is not None:
        normalized_transmission_completed_at = _normalize_utc_datetime(row.transmission_completed_at)
        if row.transmission_completed_at != normalized_transmission_completed_at:
            row.transmission_completed_at = normalized_transmission_completed_at
            changed = True

    normalized_transmission_reference = _normalize_manual_reference(row.transmission_reference)
    if row.transmission_reference != normalized_transmission_reference:
        row.transmission_reference = normalized_transmission_reference
        changed = True

    return changed


def _repair_manual_failure_fields(row: PayrollT4SubmissionJob) -> bool:
    changed = _repair_submission_job_snapshot_fields(row)

    if row.transmission_started_at is not None:
        normalized_transmission_started_at = _normalize_utc_datetime(row.transmission_started_at)
        if row.transmission_started_at != normalized_transmission_started_at:
            row.transmission_started_at = normalized_transmission_started_at
            changed = True

    if row.transmission_completed_at is not None:
        normalized_transmission_completed_at = _normalize_utc_datetime(row.transmission_completed_at)
        if row.transmission_completed_at != normalized_transmission_completed_at:
            row.transmission_completed_at = normalized_transmission_completed_at
            changed = True

    normalized_failure_code = _normalize_manual_reference(row.failure_code)
    if row.failure_code != normalized_failure_code:
        row.failure_code = normalized_failure_code
        changed = True

    normalized_failure_message = _normalize_manual_reference(row.failure_message)
    if row.failure_message != normalized_failure_message:
        row.failure_message = normalized_failure_message
        changed = True

    return changed


def _repair_manual_response_fields(row: PayrollT4SubmissionJob) -> bool:
    changed = _repair_submission_job_snapshot_fields(row)

    if row.response_recorded_at is not None:
        normalized_response_recorded_at = _normalize_utc_datetime(row.response_recorded_at)
        if row.response_recorded_at != normalized_response_recorded_at:
            row.response_recorded_at = normalized_response_recorded_at
            changed = True

    normalized_response_recorded_by_user_id = _normalize_snapshot_text(row.response_recorded_by_user_id)
    if row.response_recorded_by_user_id != normalized_response_recorded_by_user_id:
        row.response_recorded_by_user_id = normalized_response_recorded_by_user_id
        changed = True

    normalized_response_reference = _normalize_manual_reference(row.response_reference)
    if row.response_reference != normalized_response_reference:
        row.response_reference = normalized_response_reference
        changed = True

    normalized_response_code = _normalize_manual_reference(row.response_code)
    if row.response_code != normalized_response_code:
        row.response_code = normalized_response_code
        changed = True

    normalized_response_message = _normalize_manual_reference(row.response_message)
    if row.response_message != normalized_response_message:
        row.response_message = normalized_response_message
        changed = True

    return changed


def _repair_queued_submission_job_fields(row: PayrollT4SubmissionJob) -> bool:
    return _repair_submission_job_snapshot_fields(row)


def _validate_submission_artifact(
    *,
    artifact_row: PayrollT4FilingArtifact | None,
    tax_year: int,
) -> PayrollT4FilingArtifact:
    active_validator = get_active_payroll_t4_xml_validator()
    if artifact_row is None:
        raise ValueError(f"Payroll T4 filing artifact not found for tax year {int(tax_year)}")
    if not str(artifact_row.artifact_sha256 or "").strip():
        raise ValueError(f"Payroll T4 filing artifact hash is not available for tax year {int(tax_year)}")
    if (
        artifact_row.xml_package_blob is None
        or not str(artifact_row.xml_package_file_name or "").strip()
        or not str(artifact_row.xml_package_content_type or "").strip()
    ):
        raise ValueError(f"Payroll T4 XML package not found for tax year {int(tax_year)}")
    if not str(artifact_row.xml_package_sha256 or "").strip():
        raise ValueError(f"Payroll T4 XML package hash is not available for tax year {int(tax_year)}")
    if not str(artifact_row.xml_validation_status or "").strip():
        raise ValueError(f"Payroll T4 XML validation result not found for tax year {int(tax_year)}")
    if str(artifact_row.xml_validation_status) != "VALID":
        raise ValueError(f"Payroll T4 XML validation is not passing for tax year {int(tax_year)}")
    if str(artifact_row.xml_validation_xml_sha256 or "").strip() != str(artifact_row.xml_package_sha256 or "").strip():
        raise ValueError(f"Payroll T4 XML validation is stale for tax year {int(tax_year)}")
    if str(artifact_row.xml_validation_validator_id or "").strip() != active_validator.validator_id:
        raise ValueError(f"Payroll T4 XML validation validator is unsupported for tax year {int(tax_year)}")
    if str(artifact_row.xml_validation_validator_version or "").strip() != active_validator.validator_version:
        raise ValueError(f"Payroll T4 XML validation version is stale for tax year {int(tax_year)}")
    return artifact_row


def get_payroll_t4_submission_job(
    *,
    db: Session,
    company_id: int,
    submission_job_id: int,
) -> PayrollT4SubmissionJob | None:
    return (
        db.query(PayrollT4SubmissionJob)
        .filter(PayrollT4SubmissionJob.company_id == int(company_id))
        .filter(PayrollT4SubmissionJob.id == int(submission_job_id))
        .one_or_none()
    )


def list_payroll_t4_submission_jobs(
    *,
    db: Session,
    company_id: int,
    tax_year: int,
) -> list[PayrollT4SubmissionJobRecord]:
    rows = (
        db.query(PayrollT4SubmissionJob)
        .filter(PayrollT4SubmissionJob.company_id == int(company_id))
        .filter(PayrollT4SubmissionJob.tax_year == int(tax_year))
        .order_by(PayrollT4SubmissionJob.created_at.desc(), PayrollT4SubmissionJob.id.desc())
        .all()
    )
    return [
        PayrollT4SubmissionJobRecord(
            id=int(row.id),
            company_id=int(row.company_id),
            tax_year=int(row.tax_year),
            filing_artifact_id=str(_normalize_snapshot_text(row.filing_artifact_id) or ""),
            status=str(row.status),
            created_at=_normalize_utc_datetime(row.created_at),
            created_by_user_id=_normalize_snapshot_text(row.created_by_user_id),
            queued_at=_normalize_optional_utc_datetime(row.queued_at),
            transmission_started_at=_normalize_optional_utc_datetime(row.transmission_started_at),
            transmission_completed_at=_normalize_optional_utc_datetime(row.transmission_completed_at),
            transmission_reference=_normalize_snapshot_text(row.transmission_reference),
            response_status=_normalize_snapshot_upper_text(row.response_status),
            response_recorded_at=_normalize_optional_utc_datetime(row.response_recorded_at),
            response_recorded_by_user_id=_normalize_snapshot_text(row.response_recorded_by_user_id),
            response_reference=_normalize_snapshot_text(row.response_reference),
            response_code=_normalize_snapshot_text(row.response_code),
            response_message=_normalize_snapshot_text(row.response_message),
            failure_code=_normalize_snapshot_text(row.failure_code),
            failure_message=_normalize_snapshot_text(row.failure_message),
            final_outcome=_normalize_snapshot_upper_text(row.final_outcome),
            final_outcome_detail=_normalize_snapshot_text(row.final_outcome_detail),
            xml_package_sha256=str(_normalize_snapshot_text(row.xml_package_sha256) or ""),
            filing_artifact_sha256=str(_normalize_snapshot_text(row.filing_artifact_sha256) or ""),
            validation_validator_id=str(_normalize_snapshot_text(row.validation_validator_id) or ""),
            validation_validator_version=str(_normalize_snapshot_text(row.validation_validator_version) or ""),
            validation_mode=str(_normalize_snapshot_upper_text(row.validation_mode) or ""),
            validation_status=str(_normalize_snapshot_upper_text(row.validation_status) or ""),
            validated_at=_normalize_utc_datetime(row.validated_at),
            validated_by_user_id=_normalize_snapshot_text(row.validated_by_user_id),
        )
        for row in rows
    ]


def list_payroll_t4_submission_attempts(
    *,
    db: Session,
    company_id: int,
    submission_job_id: int,
) -> list[PayrollT4SubmissionAttemptRecord]:
    rows = (
        db.query(PayrollT4SubmissionAttempt)
        .filter(PayrollT4SubmissionAttempt.company_id == int(company_id))
        .filter(PayrollT4SubmissionAttempt.submission_job_id == int(submission_job_id))
        .order_by(PayrollT4SubmissionAttempt.attempt_number.asc(), PayrollT4SubmissionAttempt.id.asc())
        .all()
    )
    return [
        PayrollT4SubmissionAttemptRecord(
            id=int(row.id),
            company_id=int(row.company_id),
            submission_job_id=int(row.submission_job_id),
            attempt_number=int(row.attempt_number),
            lifecycle_state=str(row.lifecycle_state),
            validation_passed=bool(row.validation_passed),
            created_at=_normalize_utc_datetime(row.created_at),
            validated_at=_normalize_optional_utc_datetime(row.validated_at),
            queued_at=_normalize_optional_utc_datetime(row.queued_at),
            transmission_recorded_at=_normalize_optional_utc_datetime(row.transmission_recorded_at),
            response_recorded_at=_normalize_optional_utc_datetime(row.response_recorded_at),
            failure_recorded_at=_normalize_optional_utc_datetime(row.failure_recorded_at),
            response_outcome=_normalize_snapshot_upper_text(row.response_outcome),
            failure_reason=_normalize_snapshot_text(row.failure_reason),
        )
        for row in rows
    ]


def list_payroll_t4_submission_attempt_events(
    *,
    db: Session,
    company_id: int,
    submission_job_id: int,
) -> list[PayrollT4SubmissionAttemptEventRecord]:
    rows = (
        db.query(PayrollT4SubmissionAttemptEvent)
        .filter(PayrollT4SubmissionAttemptEvent.company_id == int(company_id))
        .filter(PayrollT4SubmissionAttemptEvent.submission_job_id == int(submission_job_id))
        .order_by(
            PayrollT4SubmissionAttemptEvent.event_timestamp.asc(),
            PayrollT4SubmissionAttemptEvent.attempt_number.asc(),
            PayrollT4SubmissionAttemptEvent.id.asc(),
        )
        .all()
    )
    return [
        PayrollT4SubmissionAttemptEventRecord(
            id=int(event.id),
            company_id=int(event.company_id),
            submission_job_id=int(event.submission_job_id),
            attempt_number=int(event.attempt_number),
            event_type=str(event.event_type),
            event_timestamp=_normalize_utc_datetime(event.event_timestamp),
            actor_user_id=_normalize_snapshot_text(event.actor_user_id),
            payload_json=dict(event.payload_json or {}),
        )
        for event in rows
    ]


def create_payroll_t4_submission_job(
    *,
    db: Session,
    company_id: int,
    tax_year: int,
    actor_user_id: str | None,
) -> tuple[PayrollT4SubmissionJob, bool]:
    artifact_row = _validate_submission_artifact(
        artifact_row=get_payroll_t4_filing_artifact_row(
            db=db,
            company_id=int(company_id),
            tax_year=int(tax_year),
        ),
        tax_year=int(tax_year),
    )
    artifact_sha256 = _normalize_snapshot_text(artifact_row.artifact_sha256)
    xml_hash = _normalize_snapshot_text(artifact_row.xml_package_sha256)
    validation_validator_id = _normalize_snapshot_text(artifact_row.xml_validation_validator_id)
    validation_validator_version = _normalize_snapshot_text(artifact_row.xml_validation_validator_version)
    normalized_actor_user_id = _normalize_snapshot_text(actor_user_id)
    existing = (
        db.query(PayrollT4SubmissionJob)
        .filter(PayrollT4SubmissionJob.company_id == int(company_id))
        .filter(PayrollT4SubmissionJob.tax_year == int(tax_year))
        .filter(func.btrim(PayrollT4SubmissionJob.xml_package_sha256) == xml_hash)
        .one_or_none()
    )
    if existing is not None:
        existing_changed = False
        normalized_filing_artifact_id = _normalize_snapshot_text(artifact_row.filing_artifact_id)
        if existing.filing_artifact_id != normalized_filing_artifact_id:
            existing.filing_artifact_id = normalized_filing_artifact_id
            existing_changed = True
        if _repair_submission_job_snapshot_fields(existing):
            existing_changed = True
        if existing_changed:
            db.flush()
        attempt = _sync_latest_submission_attempt_from_job(db=db, row=existing)
        _record_attempt_created_and_validation_events(
            db=db,
            row=existing,
            attempt=attempt,
            actor_user_id=existing.created_by_user_id,
        )
        return existing, False

    created_at = datetime.now(timezone.utc)
    row = PayrollT4SubmissionJob(
        company_id=int(company_id),
        tax_year=int(tax_year),
        filing_artifact_id=str(artifact_row.filing_artifact_id),
        status="PREPARED",
        created_at=created_at,
        created_by_user_id=normalized_actor_user_id,
        filing_artifact_sha256=artifact_sha256,
        xml_package_sha256=xml_hash,
        validation_validator_id=validation_validator_id,
        validation_validator_version=validation_validator_version,
        validation_mode=str(artifact_row.xml_validation_mode),
        validation_status=str(artifact_row.xml_validation_status),
        validated_at=_normalize_utc_datetime(artifact_row.xml_validated_at),
        validated_by_user_id=_normalize_snapshot_text(artifact_row.xml_validated_by_user_id),
    )
    db.add(row)
    db.flush()
    attempt = _sync_latest_submission_attempt_from_job(db=db, row=row)
    _record_attempt_created_and_validation_events(
        db=db,
        row=row,
        attempt=attempt,
        actor_user_id=actor_user_id,
    )

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=PAYROLL_T4_SUBMISSION_JOB_CREATED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "submission_job_id": int(row.id),
            "filing_artifact_id": str(row.filing_artifact_id),
            "tax_year": int(row.tax_year),
            "actor_user_id": normalized_actor_user_id,
            "status": str(row.status),
            "artifact_sha256": str(row.filing_artifact_sha256),
            "xml_hash": xml_hash,
            "xml_package_sha256": xml_hash,
            "validation_validator_id": str(row.validation_validator_id),
            "validation_validator_version": str(row.validation_validator_version),
            "validation_mode": str(row.validation_mode),
            "validation_status": str(row.validation_status),
            "validated_at": _serialize_utc_timestamp(row.validated_at),
            "validated_by_user_id": _normalize_snapshot_text(row.validated_by_user_id),
            "timestamp": _serialize_utc_timestamp(created_at),
        },
    )
    return row, True


def queue_payroll_t4_submission_job_for_transmission(
    *,
    db: Session,
    company_id: int,
    submission_job_id: int,
    actor_user_id: str | None,
) -> tuple[PayrollT4SubmissionJob, bool]:
    row = get_payroll_t4_submission_job(
        db=db,
        company_id=int(company_id),
        submission_job_id=int(submission_job_id),
    )
    if row is None:
        raise ValueError("Payroll T4 submission job not found")
    if str(row.status) != "PREPARED":
        raise ValueError("Submission job can only be queued from PREPARED status")

    already_queued = row.queued_at is not None
    queued_at = row.queued_at or datetime.now(timezone.utc)
    row_changed = False
    if row.queued_at is None:
        row.queued_at = queued_at
        row_changed = True
    if _repair_queued_submission_job_fields(row):
        row_changed = True
    if row_changed:
        db.flush()
    attempt = _sync_latest_submission_attempt_from_job(db=db, row=row)

    filing_artifact_id = _normalize_snapshot_text(row.filing_artifact_id)
    artifact_sha256 = _normalize_snapshot_text(row.filing_artifact_sha256)
    xml_package_sha256 = _normalize_snapshot_text(row.xml_package_sha256)
    validation_validator_id = _normalize_snapshot_text(row.validation_validator_id)
    validation_validator_version = _normalize_snapshot_text(row.validation_validator_version)
    validation_mode = _normalize_snapshot_upper_text(row.validation_mode)
    validation_status = _normalize_snapshot_upper_text(row.validation_status)
    normalized_actor_user_id = _normalize_snapshot_text(actor_user_id)
    idempotency_key = f"PAYROLL_T4_SUBMISSION_JOB_QUEUED:{int(company_id)}:{int(row.id)}"
    payload = {
        "submission_job_id": int(row.id),
        "company_id": int(company_id),
        "status": str(row.status),
        "tax_year": int(row.tax_year),
        "filing_artifact_id": filing_artifact_id,
        "xml_package_sha256": xml_package_sha256,
        "artifact_sha256": artifact_sha256,
        "validation_validator_id": validation_validator_id,
        "validation_validator_version": validation_validator_version,
        "validation_mode": validation_mode,
        "validation_status": validation_status,
        "validated_at": _serialize_utc_timestamp(row.validated_at),
        "validated_by_user_id": _normalize_snapshot_text(row.validated_by_user_id),
        "queued_at": _serialize_utc_timestamp(queued_at),
    }
    existing_outbox = (
        db.query(EventOutbox)
        .filter(EventOutbox.company_id == int(company_id))
        .filter(EventOutbox.event_type == "PAYROLL_T4_SUBMISSION_JOB_QUEUED")
        .filter(EventOutbox.idempotency_key == idempotency_key)
        .one_or_none()
    )
    if existing_outbox is None:
        db.add(
            EventOutbox(
                company_id=int(company_id),
                event_type="PAYROLL_T4_SUBMISSION_JOB_QUEUED",
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
    elif (
        existing_outbox.processed is False
        and _normalize_queued_submission_job_payload(existing_outbox.payload) != payload
    ):
        existing_outbox.payload = payload
        db.flush()

    if already_queued:
        _record_submission_attempt_event(
            db=db,
            row=row,
            attempt_number=int(attempt.attempt_number),
            event_type="QUEUED",
            actor_user_id=actor_user_id,
            event_timestamp=queued_at,
            payload_json=_build_attempt_event_payload(
                row=row,
                attempt_number=int(attempt.attempt_number),
                event_type="QUEUED",
                actor_user_id=actor_user_id,
            ),
        )
        return row, False

    _record_submission_attempt_event(
        db=db,
        row=row,
        attempt_number=int(attempt.attempt_number),
        event_type="QUEUED",
        actor_user_id=actor_user_id,
        event_timestamp=queued_at,
        payload_json=_build_attempt_event_payload(
            row=row,
            attempt_number=int(attempt.attempt_number),
            event_type="QUEUED",
            actor_user_id=actor_user_id,
        ),
    )

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=PAYROLL_T4_SUBMISSION_JOB_QUEUED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "submission_job_id": int(row.id),
            "filing_artifact_id": filing_artifact_id,
            "tax_year": int(row.tax_year),
            "actor_user_id": normalized_actor_user_id,
            "status": str(row.status),
            "artifact_sha256": artifact_sha256,
            "xml_hash": xml_package_sha256,
            "xml_package_sha256": xml_package_sha256,
            "validation_validator_id": validation_validator_id,
            "validation_validator_version": validation_validator_version,
            "validation_mode": validation_mode,
            "validation_status": validation_status,
            "validated_at": _serialize_utc_timestamp(row.validated_at),
            "validated_by_user_id": _normalize_snapshot_text(row.validated_by_user_id),
            "queued_at": _serialize_utc_timestamp(queued_at),
            "timestamp": _serialize_utc_timestamp(queued_at),
        },
    )
    return row, True


def record_payroll_t4_submission_job_manual_transmission(
    *,
    db: Session,
    company_id: int,
    submission_job_id: int,
    transmission_reference: str | None,
    actor_user_id: str | None,
) -> tuple[PayrollT4SubmissionJob, bool]:
    row = get_payroll_t4_submission_job(
        db=db,
        company_id=int(company_id),
        submission_job_id=int(submission_job_id),
    )
    if row is None:
        raise ValueError("Payroll T4 submission job not found")

    normalized_reference = _normalize_manual_reference(transmission_reference)
    if normalized_reference is None:
        raise ValueError("transmission_reference is required")

    if str(row.status) == "TRANSMISSION_RECORDED_MANUAL":
        if _normalize_manual_reference(row.transmission_reference) == normalized_reference:
            if _repair_manual_transmission_fields(row):
                db.flush()
            attempt = _sync_latest_submission_attempt_from_job(db=db, row=row)
            _record_submission_attempt_event(
                db=db,
                row=row,
                attempt_number=int(attempt.attempt_number),
                event_type="TRANSMISSION_RECORDED",
                actor_user_id=actor_user_id,
                event_timestamp=_normalize_utc_datetime(row.transmission_completed_at),
                payload_json=_build_attempt_event_payload(
                    row=row,
                    attempt_number=int(attempt.attempt_number),
                    event_type="TRANSMISSION_RECORDED",
                    actor_user_id=actor_user_id,
                ),
            )
            return row, False
        raise ValueError("Manual transmission already recorded for this submission job")
    if str(row.status) != "PREPARED":
        raise ValueError("Manual transmission can only be recorded from PREPARED status")

    normalized_actor_user_id = _normalize_snapshot_text(actor_user_id)
    recorded_at = datetime.now(timezone.utc)
    row.status = "TRANSMISSION_RECORDED_MANUAL"
    row.transmission_started_at = recorded_at
    row.transmission_completed_at = recorded_at
    row.transmission_reference = normalized_reference
    db.flush()
    attempt = _sync_latest_submission_attempt_from_job(db=db, row=row)

    _record_submission_attempt_event(
        db=db,
        row=row,
        attempt_number=int(attempt.attempt_number),
        event_type="TRANSMISSION_RECORDED",
        actor_user_id=actor_user_id,
        event_timestamp=recorded_at,
        payload_json=_build_attempt_event_payload(
            row=row,
            attempt_number=int(attempt.attempt_number),
            event_type="TRANSMISSION_RECORDED",
            actor_user_id=actor_user_id,
        ),
    )

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=PAYROLL_T4_SUBMISSION_JOB_MANUAL_TRANSMISSION_RECORDED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "submission_job_id": int(row.id),
            "filing_artifact_id": _normalize_snapshot_text(row.filing_artifact_id),
            "tax_year": int(row.tax_year),
            "actor_user_id": normalized_actor_user_id,
            "status": str(row.status),
            "transmission_reference": row.transmission_reference,
            "timestamp": recorded_at.isoformat(),
            **_build_canonical_validation_snapshot_payload(row),
        },
    )
    return row, True


def record_payroll_t4_submission_job_manual_response(
    *,
    db: Session,
    company_id: int,
    submission_job_id: int,
    response_status: str | None,
    response_reference: str | None,
    response_code: str | None,
    response_message: str | None,
    actor_user_id: str | None,
) -> tuple[PayrollT4SubmissionJob, bool]:
    row = get_payroll_t4_submission_job(
        db=db,
        company_id=int(company_id),
        submission_job_id=int(submission_job_id),
    )
    if row is None:
        raise ValueError("Payroll T4 submission job not found")

    normalized_status = _normalize_manual_response_status(response_status)
    if normalized_status is None:
        raise ValueError("response_status is required")
    normalized_reference = _normalize_manual_reference(response_reference)
    normalized_code = _normalize_manual_reference(response_code)
    normalized_message = _normalize_manual_reference(response_message)
    if normalized_reference is None and normalized_code is None and normalized_message is None:
        raise ValueError("At least one response metadata field is required")
    if normalized_status == "REJECTED" and normalized_code is None and normalized_message is None:
        raise ValueError("Rejected responses require response_code or response_message")

    target_status = (
        "RESPONSE_ACCEPTED_MANUAL"
        if normalized_status == "ACCEPTED"
        else "RESPONSE_REJECTED_MANUAL"
    )
    current_status = str(row.status)
    if current_status in {"RESPONSE_ACCEPTED_MANUAL", "RESPONSE_REJECTED_MANUAL"}:
        if (
            current_status == target_status
            and _normalize_manual_reference(row.response_reference) == normalized_reference
            and _normalize_manual_reference(row.response_code) == normalized_code
            and _normalize_manual_reference(row.response_message) == normalized_message
        ):
            if _repair_manual_response_fields(row):
                db.flush()
            attempt = _sync_latest_submission_attempt_from_job(db=db, row=row)
            _record_submission_attempt_event(
                db=db,
                row=row,
                attempt_number=int(attempt.attempt_number),
                event_type="RESPONSE_ACCEPTED" if normalized_status == "ACCEPTED" else "RESPONSE_REJECTED",
                actor_user_id=actor_user_id,
                event_timestamp=_normalize_utc_datetime(row.response_recorded_at),
                payload_json=_build_attempt_event_payload(
                    row=row,
                    attempt_number=int(attempt.attempt_number),
                    event_type="RESPONSE_ACCEPTED" if normalized_status == "ACCEPTED" else "RESPONSE_REJECTED",
                    actor_user_id=actor_user_id,
                ),
            )
            return row, False
        raise ValueError("CRA response already recorded for this submission job")
    if current_status != "TRANSMISSION_RECORDED_MANUAL":
        raise ValueError("CRA response can only be recorded after transmission is recorded")

    normalized_actor_user_id = _normalize_snapshot_text(actor_user_id)
    recorded_at = datetime.now(timezone.utc)
    row.status = target_status
    row.response_status = normalized_status
    row.response_recorded_at = recorded_at
    row.response_recorded_by_user_id = normalized_actor_user_id
    row.response_reference = normalized_reference
    row.response_code = normalized_code
    row.response_message = normalized_message
    row.final_outcome = "ACCEPTED" if normalized_status == "ACCEPTED" else "REJECTED"
    row.final_outcome_detail = normalized_message or normalized_code or normalized_reference
    db.flush()
    attempt = _sync_latest_submission_attempt_from_job(db=db, row=row)

    _record_submission_attempt_event(
        db=db,
        row=row,
        attempt_number=int(attempt.attempt_number),
        event_type="RESPONSE_ACCEPTED" if normalized_status == "ACCEPTED" else "RESPONSE_REJECTED",
        actor_user_id=actor_user_id,
        event_timestamp=recorded_at,
        payload_json=_build_attempt_event_payload(
            row=row,
            attempt_number=int(attempt.attempt_number),
            event_type="RESPONSE_ACCEPTED" if normalized_status == "ACCEPTED" else "RESPONSE_REJECTED",
            actor_user_id=actor_user_id,
        ),
    )

    event_type = (
        PAYROLL_T4_SUBMISSION_JOB_MANUAL_RESPONSE_ACCEPTED_EVENT
        if normalized_status == "ACCEPTED"
        else PAYROLL_T4_SUBMISSION_JOB_MANUAL_RESPONSE_REJECTED_EVENT
    )
    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=event_type,
        actor_user_id=actor_user_id,
        payload_json={
            "submission_job_id": int(row.id),
            "filing_artifact_id": _normalize_snapshot_text(row.filing_artifact_id),
            "tax_year": int(row.tax_year),
            "actor_user_id": normalized_actor_user_id,
            "status": str(row.status),
            "response_status": row.response_status,
            "response_reference": row.response_reference,
            "response_code": row.response_code,
            "response_message": row.response_message,
            "response_recorded_at": row.response_recorded_at.astimezone(timezone.utc).isoformat(),
            "response_recorded_by_user_id": _normalize_snapshot_text(row.response_recorded_by_user_id),
            "timestamp": recorded_at.isoformat(),
            **_build_canonical_validation_snapshot_payload(row),
        },
    )
    return row, True


def record_payroll_t4_submission_job_manual_failure(
    *,
    db: Session,
    company_id: int,
    submission_job_id: int,
    failure_code: str | None,
    failure_message: str | None,
    actor_user_id: str | None,
) -> tuple[PayrollT4SubmissionJob, bool]:
    row = get_payroll_t4_submission_job(
        db=db,
        company_id=int(company_id),
        submission_job_id=int(submission_job_id),
    )
    if row is None:
        raise ValueError("Payroll T4 submission job not found")

    normalized_code = _normalize_manual_reference(failure_code)
    normalized_message = _normalize_manual_reference(failure_message)
    if normalized_code is None and normalized_message is None:
        raise ValueError("failure_code or failure_message is required")

    current_status = str(row.status)
    if current_status in {"RESPONSE_ACCEPTED_MANUAL", "RESPONSE_REJECTED_MANUAL"}:
        raise ValueError("Manual failure cannot be recorded after CRA response is recorded")
    if current_status == "FAILED_MANUAL":
        if (
            _normalize_manual_reference(row.failure_code) == normalized_code
            and _normalize_manual_reference(row.failure_message) == normalized_message
        ):
            if _repair_manual_failure_fields(row):
                db.flush()
            attempt = _sync_latest_submission_attempt_from_job(db=db, row=row)
            _record_submission_attempt_event(
                db=db,
                row=row,
                attempt_number=int(attempt.attempt_number),
                event_type="FAILURE_RECORDED",
                actor_user_id=actor_user_id,
                event_timestamp=_derive_attempt_failure_recorded_at(row),
                payload_json=_build_attempt_event_payload(
                    row=row,
                    attempt_number=int(attempt.attempt_number),
                    event_type="FAILURE_RECORDED",
                    actor_user_id=actor_user_id,
                ),
            )
            return row, False
        raise ValueError("Manual failure already recorded for this submission job")
    if current_status not in {"PREPARED", "TRANSMISSION_RECORDED_MANUAL"}:
        raise ValueError("Manual failure can only be recorded from PREPARED or TRANSMISSION_RECORDED_MANUAL status")

    normalized_actor_user_id = _normalize_snapshot_text(actor_user_id)
    recorded_at = datetime.now(timezone.utc)
    row.status = "FAILED_MANUAL"
    row.failure_code = normalized_code
    row.failure_message = normalized_message
    row.final_outcome = "FAILED_MANUAL"
    row.final_outcome_detail = normalized_message or normalized_code
    db.flush()
    attempt = _sync_latest_submission_attempt_from_job(db=db, row=row)

    _record_submission_attempt_event(
        db=db,
        row=row,
        attempt_number=int(attempt.attempt_number),
        event_type="FAILURE_RECORDED",
        actor_user_id=actor_user_id,
        event_timestamp=recorded_at,
        payload_json=_build_attempt_event_payload(
            row=row,
            attempt_number=int(attempt.attempt_number),
            event_type="FAILURE_RECORDED",
            actor_user_id=actor_user_id,
        ),
    )

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=PAYROLL_T4_SUBMISSION_JOB_MANUAL_FAILURE_RECORDED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "submission_job_id": int(row.id),
            "filing_artifact_id": _normalize_snapshot_text(row.filing_artifact_id),
            "tax_year": int(row.tax_year),
            "actor_user_id": normalized_actor_user_id,
            "status": str(row.status),
            "failure_code": row.failure_code,
            "failure_message": row.failure_message,
            "timestamp": recorded_at.isoformat(),
            **_build_canonical_validation_snapshot_payload(row),
        },
    )
    return row, True


def retry_payroll_t4_submission_job(
    *,
    db: Session,
    company_id: int,
    submission_job_id: int,
    actor_user_id: str | None,
) -> tuple[PayrollT4SubmissionJob, bool]:
    row = get_payroll_t4_submission_job(
        db=db,
        company_id=int(company_id),
        submission_job_id=int(submission_job_id),
    )
    if row is None:
        raise ValueError("Payroll T4 submission job not found")

    latest_attempt = _get_latest_submission_attempt(
        db=db,
        company_id=int(company_id),
        submission_job_id=int(submission_job_id),
    )
    current_status = str(row.status)

    if current_status == "PREPARED" and latest_attempt is not None and int(latest_attempt.attempt_number) > 1:
        if _repair_submission_job_snapshot_fields(row):
            db.flush()
        _record_attempt_created_and_validation_events(
            db=db,
            row=row,
            attempt=latest_attempt,
            actor_user_id=actor_user_id,
        )
        return row, False

    if current_status not in {"FAILED_MANUAL", "RESPONSE_REJECTED_MANUAL"}:
        raise ValueError("Submission job can only be retried from FAILED_MANUAL or RESPONSE_REJECTED_MANUAL status")

    prior_attempt_number = None if latest_attempt is None else int(latest_attempt.attempt_number)
    normalized_actor_user_id = _normalize_snapshot_text(actor_user_id)

    row.status = "PREPARED"
    row.queued_at = None
    row.transmission_started_at = None
    row.transmission_completed_at = None
    row.transmission_reference = None
    row.response_status = None
    row.response_recorded_at = None
    row.response_recorded_by_user_id = None
    row.response_reference = None
    row.response_code = None
    row.response_message = None
    row.failure_code = None
    row.failure_message = None

    if _repair_submission_job_snapshot_fields(row):
        db.flush()
    else:
        db.flush()

    retried_at = datetime.now(timezone.utc)
    new_attempt = _build_retry_attempt(db=db, row=row)

    if prior_attempt_number is not None:
        _record_submission_attempt_event(
            db=db,
            row=row,
            attempt_number=int(prior_attempt_number),
            event_type="RETRIED",
            actor_user_id=actor_user_id,
            event_timestamp=retried_at,
            payload_json={
                "submission_job_id": int(row.id),
                "attempt_number": int(prior_attempt_number),
                "retried_to_attempt_number": int(new_attempt.attempt_number),
                "status": str(row.status),
                "actor_user_id": normalized_actor_user_id,
            },
        )
    _record_attempt_created_and_validation_events(
        db=db,
        row=row,
        attempt=new_attempt,
        actor_user_id=actor_user_id,
    )

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=PAYROLL_T4_SUBMISSION_JOB_RETRIED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "submission_job_id": int(row.id),
            "filing_artifact_id": _normalize_snapshot_text(row.filing_artifact_id),
            "tax_year": int(row.tax_year),
            "actor_user_id": normalized_actor_user_id,
            "status": str(row.status),
            "prior_attempt_number": prior_attempt_number,
            "attempt_number": int(new_attempt.attempt_number),
            "timestamp": retried_at.isoformat(),
            **_build_canonical_validation_snapshot_payload(row),
        },
    )
    return row, True

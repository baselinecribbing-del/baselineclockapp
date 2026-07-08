from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.payroll_run import PayrollRun
from app.services.payroll_audit_service import (
    PAYROLL_RUN_MARKED_SUPERSEDED_EVENT,
    record_payroll_audit_event,
)


def _get_payroll_run(*, db: Session, company_id: int, payroll_run_id: str) -> PayrollRun | None:
    return (
        db.query(PayrollRun)
        .filter(PayrollRun.company_id == int(company_id))
        .filter(PayrollRun.payroll_run_id == str(payroll_run_id))
        .one_or_none()
    )


def mark_payroll_run_superseded(
    *,
    db: Session,
    company_id: int,
    payroll_run_id: str,
    superseded_by_payroll_run_id: str | None,
    correction_reason: str | None,
    actor_user_id: str | None,
) -> tuple[PayrollRun, bool]:
    row = _get_payroll_run(db=db, company_id=int(company_id), payroll_run_id=str(payroll_run_id))
    if row is None:
        raise ValueError("PayrollRun not found")
    if str(row.status) != "FINALIZED":
        raise ValueError("Only FINALIZED payroll runs can be marked superseded")

    normalized_reason = None if correction_reason is None else str(correction_reason).strip() or None
    normalized_replacement_run_id = (
        None if superseded_by_payroll_run_id is None else str(superseded_by_payroll_run_id).strip() or None
    )
    if normalized_reason is None:
        raise ValueError("correction_reason is required when marking a payroll run superseded")

    replacement_run: PayrollRun | None = None
    if normalized_replacement_run_id is not None:
        if normalized_replacement_run_id == str(row.payroll_run_id):
            raise ValueError("A payroll run cannot supersede itself")
        replacement_run = _get_payroll_run(
            db=db,
            company_id=int(company_id),
            payroll_run_id=normalized_replacement_run_id,
        )
        if replacement_run is None:
            raise ValueError("Superseding PayrollRun not found")
        if str(replacement_run.status) not in {"FINALIZED", "POSTED"}:
            raise ValueError("Superseding PayrollRun must be FINALIZED or POSTED")

    if row.superseded_at is not None:
        if (
            str(row.superseded_by_payroll_run_id or "") == str(normalized_replacement_run_id or "")
            and str(row.correction_reason or "") == str(normalized_reason or "")
        ):
            return row, False
        raise ValueError("PayrollRun is already marked superseded")

    superseded_at = datetime.now(timezone.utc)
    row.superseded_at = superseded_at
    row.superseded_by_user_id = None if actor_user_id is None else str(actor_user_id)
    row.superseded_by_payroll_run_id = normalized_replacement_run_id
    row.correction_reason = normalized_reason
    db.flush()

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(row.payroll_run_id),
        event_type=PAYROLL_RUN_MARKED_SUPERSEDED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "payroll_run_id": str(row.payroll_run_id),
            "superseded_by_payroll_run_id": normalized_replacement_run_id,
            "correction_reason": normalized_reason,
            "actor_user_id": actor_user_id,
            "timestamp": superseded_at.isoformat(),
        },
    )
    return row, True

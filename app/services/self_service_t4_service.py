from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.payroll_t4 import PayrollT4
from app.services.payroll_audit_service import (
    PAYROLL_T4_ACKNOWLEDGED_BY_EMPLOYEE_EVENT,
    record_payroll_audit_event,
)
from app.services.payroll_t4_output_service import acknowledge_t4_employee_access
from app.services.payroll_t4_storage_service import load_t4_slip_artifact
from app.services.payroll_t4_service import PayrollT4ListRecord, list_payroll_t4s


def list_self_service_t4s(*, db: Session, company_id: int, employee_id: int) -> list[PayrollT4ListRecord]:
    return list_payroll_t4s(
        db=db,
        company_id=int(company_id),
        employee_id=int(employee_id),
    )


def get_self_service_t4(*, db: Session, company_id: int, employee_id: int, t4_id: str) -> PayrollT4 | None:
    return (
        db.query(PayrollT4)
        .filter(PayrollT4.company_id == int(company_id))
        .filter(PayrollT4.employee_id == int(employee_id))
        .filter(PayrollT4.t4_id == str(t4_id))
        .one_or_none()
    )


def acknowledge_self_service_t4(
    *,
    db: Session,
    company_id: int,
    employee_id: int,
    t4_id: str,
    actor_user_id: str | None,
) -> tuple[PayrollT4, bool]:
    row = get_self_service_t4(
        db=db,
        company_id=int(company_id),
        employee_id=int(employee_id),
        t4_id=str(t4_id),
    )
    if row is None:
        raise ValueError("T4 record not found")
    if str(row.slip_status) != "AVAILABLE" or load_t4_slip_artifact(row) is None:
        raise ValueError("T4 slip is not available")

    already_acknowledged = row.employee_acknowledged_at is not None
    acknowledge_t4_employee_access(row, actor_user_id=actor_user_id)
    db.flush()
    if already_acknowledged:
        return row, False

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=PAYROLL_T4_ACKNOWLEDGED_BY_EMPLOYEE_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "t4_id": str(row.t4_id),
            "employee_id": int(row.employee_id),
            "tax_year": int(row.tax_year),
            "employee_acknowledged_at": (
                None if row.employee_acknowledged_at is None else row.employee_acknowledged_at.isoformat()
            ),
            "employee_acknowledged_by_user_id": row.employee_acknowledged_by_user_id,
        },
    )
    return row, True

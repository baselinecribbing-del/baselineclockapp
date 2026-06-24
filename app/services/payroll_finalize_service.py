from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.pay_period import PayPeriod
from app.models.payroll_deduction import PayrollDeduction
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.models.paystub import Paystub
from app.services.payroll_audit_service import PAYROLL_RUN_FINALIZED_EVENT, record_payroll_audit_event
from app.services.payroll_remittance_service import ensure_payroll_remittance_obligation_for_run
from app.services.deduction_engine import generate_deductions_for_run
from app.services.paystub_service import generate_paystubs_for_run
from app.services.source_deduction_summary_service import (
    FEDERAL_TAX_CODES,
    PROVINCIAL_TAX_CODES,
    get_source_deduction_summary,
)


def _load_payroll_run(*, db: Session, company_id: int, payroll_run_id: str) -> PayrollRun:
    payroll_run = (
        db.query(PayrollRun)
        .filter(PayrollRun.company_id == int(company_id))
        .filter(PayrollRun.payroll_run_id == str(payroll_run_id))
        .one_or_none()
    )
    if payroll_run is None:
        raise ValueError("PayrollRun not found")
    return payroll_run


def _load_pay_period(*, db: Session, company_id: int, pay_period_id: str) -> PayPeriod:
    pay_period = (
        db.query(PayPeriod)
        .filter(PayPeriod.company_id == int(company_id))
        .filter(PayPeriod.pay_period_id == str(pay_period_id))
        .one_or_none()
    )
    if pay_period is None:
        raise ValueError("PayPeriod not found")
    return pay_period


def _item_totals_by_employee(*, db: Session, company_id: int, payroll_run_id: str) -> dict[int, int]:
    rows = (
        db.query(
            PayrollItem.employee_id,
            func.coalesce(func.sum(PayrollItem.gross_pay_cents), 0),
        )
        .filter(PayrollItem.company_id == int(company_id))
        .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
        .group_by(PayrollItem.employee_id)
        .all()
    )
    return {int(employee_id): int(gross_pay_cents or 0) for employee_id, gross_pay_cents in rows}


def _paystubs_for_run(*, db: Session, company_id: int, payroll_run_id: str) -> list[Paystub]:
    return (
        db.query(Paystub)
        .filter(Paystub.company_id == int(company_id))
        .filter(Paystub.payroll_run_id == str(payroll_run_id))
        .order_by(Paystub.employee_id.asc(), Paystub.paystub_id.asc())
        .all()
    )


def _deduction_rows_for_run(*, db: Session, company_id: int, payroll_run_id: str) -> list[PayrollDeduction]:
    return (
        db.query(PayrollDeduction)
        .filter(PayrollDeduction.company_id == int(company_id))
        .filter(PayrollDeduction.payroll_run_id == str(payroll_run_id))
        .order_by(PayrollDeduction.employee_id.asc(), PayrollDeduction.deduction_id.asc())
        .all()
    )


def _validate_finalize_consistency(
    *,
    db: Session,
    company_id: int,
    payroll_run_id: str,
    require_paystubs: bool,
) -> dict[str, Any]:
    item_totals = _item_totals_by_employee(db=db, company_id=int(company_id), payroll_run_id=str(payroll_run_id))
    if not item_totals:
        raise ValueError("Payroll run must contain payroll items before finalization")

    paystubs = _paystubs_for_run(db=db, company_id=int(company_id), payroll_run_id=str(payroll_run_id))
    paystubs_by_employee = {int(paystub.employee_id): paystub for paystub in paystubs}
    if require_paystubs and set(paystubs_by_employee.keys()) != set(item_totals.keys()):
        raise ValueError("Finalized payroll run must have one paystub per payroll employee")
    if not require_paystubs and set(paystubs_by_employee.keys()) - set(item_totals.keys()):
        raise ValueError("Paystubs cannot exist for employees outside the payroll run item set")

    deduction_rows = _deduction_rows_for_run(db=db, company_id=int(company_id), payroll_run_id=str(payroll_run_id))
    deduction_totals_by_paystub: dict[str, int] = {}
    source_deduction_count = 0
    source_deduction_total_cents = 0

    statutory_codes = {"CPP", "EI"} | FEDERAL_TAX_CODES | PROVINCIAL_TAX_CODES
    for deduction in deduction_rows:
        if deduction.paystub_id is not None:
            deduction_totals_by_paystub[str(deduction.paystub_id)] = deduction_totals_by_paystub.get(
                str(deduction.paystub_id),
                0,
            ) + int(deduction.amount_cents or 0)
        if str(deduction.deduction_type) in statutory_codes:
            source_deduction_count += 1
            source_deduction_total_cents += int(deduction.amount_cents or 0)

    for employee_id, expected_gross_pay_cents in item_totals.items():
        paystub = paystubs_by_employee.get(int(employee_id))
        if paystub is None:
            if require_paystubs:
                raise ValueError("Finalized payroll run must have one paystub per payroll employee")
            continue
        if int(paystub.gross_pay_cents or 0) != int(expected_gross_pay_cents):
            raise ValueError("Paystub gross pay must match payroll item totals before finalization")
        total_deductions_cents = int(deduction_totals_by_paystub.get(str(paystub.paystub_id), 0))
        if int(paystub.total_deductions_cents or 0) != total_deductions_cents:
            raise ValueError("Paystub deduction totals are inconsistent with payroll deductions")
        expected_net_pay_cents = int(paystub.gross_pay_cents or 0) - total_deductions_cents
        if int(paystub.net_pay_cents or 0) != expected_net_pay_cents:
            raise ValueError("Paystub net pay must equal gross pay less deductions before finalization")

    source_deduction_summary = get_source_deduction_summary(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
    )
    reported_total = int(source_deduction_summary["remittance_totals"]["employee_portions_cents"] or 0)
    if reported_total != source_deduction_total_cents:
        raise ValueError("Source deduction summary is inconsistent with payroll deductions")

    return {
        "payroll_items": int(sum(1 for _employee_id in item_totals)),
        "employee_count": int(len(item_totals)),
        "paystubs": int(len(paystubs)),
        "payroll_deductions": int(len(deduction_rows)),
        "source_deductions": {
            "row_count": int(source_deduction_count),
            "employee_portions_cents": int(reported_total),
            "approval_status": str(source_deduction_summary["approval_status"]),
        },
    }


def finalize_payroll_run(
    *,
    db: Session,
    company_id: int,
    payroll_run_id: str,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    db.flush()
    payroll_run = _load_payroll_run(db=db, company_id=int(company_id), payroll_run_id=str(payroll_run_id))
    _load_pay_period(db=db, company_id=int(company_id), pay_period_id=str(payroll_run.pay_period_id))

    if str(payroll_run.status) == "FINALIZED":
        consistency = _validate_finalize_consistency(
            db=db,
            company_id=int(company_id),
            payroll_run_id=str(payroll_run_id),
            require_paystubs=True,
        )
        ensure_payroll_remittance_obligation_for_run(
            db=db,
            company_id=int(company_id),
            payroll_run_id=str(payroll_run_id),
            actor_user_id=actor_user_id,
        )
        return {
            "ok": True,
            "payroll_run_id": str(payroll_run_id),
            "status": str(payroll_run.status),
            "paystubs": {
                "generated": 0,
                "skipped": int(consistency["paystubs"]),
                "total": int(consistency["paystubs"]),
            },
            "deductions": {
                "generated": 0,
                "skipped": int(consistency["payroll_deductions"]),
                "total": int(consistency["payroll_deductions"]),
            },
            "consistency": {
                "employee_count": int(consistency["employee_count"]),
                "payroll_item_employee_count": int(consistency["employee_count"]),
                "paystub_count": int(consistency["paystubs"]),
                "deduction_row_count": int(consistency["payroll_deductions"]),
                "source_deduction_row_count": int(consistency["source_deductions"]["row_count"]),
                "source_deduction_employee_portions_cents": int(
                    consistency["source_deductions"]["employee_portions_cents"]
                ),
                "source_deduction_approval_status": str(consistency["source_deductions"]["approval_status"]),
            },
        }

    if str(payroll_run.status) != "DRAFT":
        raise ValueError("Only DRAFT payroll runs can be finalized")
    if payroll_run.posted_at is not None:
        raise ValueError("DRAFT payroll runs must not be posted")

    _validate_finalize_consistency(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
        require_paystubs=False,
    )

    payroll_run.status = "FINALIZED"
    db.flush()

    paystub_result = generate_paystubs_for_run(
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
        db=db,
    )
    db.flush()
    deduction_result = generate_deductions_for_run(
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
        db=db,
    )
    db.flush()

    consistency = _validate_finalize_consistency(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
        require_paystubs=True,
    )
    finalized_at = datetime.now(timezone.utc)
    payroll_run.finalized_at = finalized_at
    payroll_run.finalized_by_user_id = None if actor_user_id is None else str(actor_user_id)
    payroll_run.finalize_consistency_snapshot = consistency
    db.flush()

    ensure_payroll_remittance_obligation_for_run(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
        actor_user_id=actor_user_id,
    )

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
        event_type=PAYROLL_RUN_FINALIZED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "status": str(payroll_run.status),
            "finalized_at": finalized_at.isoformat(),
            "consistency": consistency,
        },
    )

    return {
        "ok": True,
        "payroll_run_id": str(payroll_run_id),
        "status": str(payroll_run.status),
        "paystubs": {
            "generated": int(paystub_result["generated"]),
            "skipped": int(paystub_result["skipped"]),
            "total": int(consistency["paystubs"]),
        },
        "deductions": {
            "generated": int(deduction_result["generated"]),
            "skipped": int(deduction_result["skipped"]),
            "total": int(consistency["payroll_deductions"]),
        },
        "consistency": {
            "employee_count": int(consistency["employee_count"]),
            "payroll_item_employee_count": int(consistency["employee_count"]),
            "paystub_count": int(consistency["paystubs"]),
            "deduction_row_count": int(consistency["payroll_deductions"]),
            "source_deduction_row_count": int(consistency["source_deductions"]["row_count"]),
            "source_deduction_employee_portions_cents": int(
                consistency["source_deductions"]["employee_portions_cents"]
            ),
            "source_deduction_approval_status": str(consistency["source_deductions"]["approval_status"]),
        },
    }

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.pay_period import PayPeriod
from app.models.payroll_deduction import PayrollDeduction
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.models.paystub import Paystub
from app.models.time_entry import TimeEntry
from app.services.payroll_audit_service import (
    PAYROLL_RUN_CREATED_EVENT,
    PAYROLL_RUN_EXECUTED_EVENT,
    record_payroll_audit_event,
)
from app.services.deduction_engine import generate_deductions_for_run
from app.services.payroll_finalize_service import finalize_payroll_run
from app.services.payroll_builder import build_payroll_items_for_run
from app.services.payroll_processing_service import get_payroll_processing_overview
from app.services.paystub_service import generate_paystubs_for_run


class PayrollExecutionConflictError(Exception):
    def __init__(self, detail: str | dict[str, Any]) -> None:
        super().__init__(str(detail))
        self.detail = detail


@dataclass
class PayrollExecutionContext:
    pay_period: PayPeriod
    payroll_run: PayrollRun
    run_created: bool
    items_created: int


def _pending_time_entries_for_pay_period(
    *,
    db: Session,
    company_id: int,
    pay_period: PayPeriod,
) -> tuple[int, list[str]]:
    pending_ids = (
        db.query(TimeEntry.time_entry_id)
        .join(
            Employee,
            (Employee.id == TimeEntry.employee_id) & (Employee.company_id == TimeEntry.company_id),
        )
        .filter(TimeEntry.company_id == int(company_id))
        .filter(TimeEntry.status == "completed")
        .filter(TimeEntry.approval_status == "pending")
        .filter(Employee.requires_payroll.is_(True))
        .filter(func.date(TimeEntry.started_at) >= pay_period.start_date)
        .filter(func.date(TimeEntry.started_at) <= pay_period.end_date)
        .filter(
            ~TimeEntry.time_entry_id.in_(
                db.query(PayrollItem.source_time_entry_id)
                .filter(PayrollItem.company_id == int(company_id))
                .filter(PayrollItem.source_time_entry_id.isnot(None))
            )
        )
        .order_by(TimeEntry.started_at.asc(), TimeEntry.time_entry_id.asc())
        .all()
    )
    ids = [str(row[0]) for row in pending_ids]
    return len(ids), ids[:10]


def _resolve_pay_period(*, db: Session, company_id: int, pay_period_id: str | None, payroll_run_id: str | None) -> tuple[PayPeriod, PayrollRun | None]:
    if payroll_run_id is not None:
        payroll_run = (
            db.query(PayrollRun)
            .filter(PayrollRun.company_id == int(company_id))
            .filter(PayrollRun.payroll_run_id == str(payroll_run_id))
            .one_or_none()
        )
        if payroll_run is None:
            raise ValueError("PayrollRun not found")
        pay_period = (
            db.query(PayPeriod)
            .filter(PayPeriod.company_id == int(company_id))
            .filter(PayPeriod.pay_period_id == str(payroll_run.pay_period_id))
            .one_or_none()
        )
        if pay_period is None:
            raise ValueError("PayPeriod not found")
        return pay_period, payroll_run

    if pay_period_id is not None:
        pay_period = (
            db.query(PayPeriod)
            .filter(PayPeriod.company_id == int(company_id))
            .filter(PayPeriod.pay_period_id == str(pay_period_id))
            .one_or_none()
        )
        if pay_period is None:
            raise ValueError("PayPeriod not found")
        payroll_run = (
            db.query(PayrollRun)
            .filter(PayrollRun.company_id == int(company_id))
            .filter(PayrollRun.pay_period_id == str(pay_period.pay_period_id))
            .one_or_none()
        )
        return pay_period, payroll_run

    today = date.today()
    current_periods = (
        db.query(PayPeriod)
        .filter(PayPeriod.company_id == int(company_id))
        .filter(PayPeriod.status == "OPEN")
        .filter(PayPeriod.start_date <= today)
        .filter(PayPeriod.end_date >= today)
        .order_by(PayPeriod.start_date.asc(), PayPeriod.pay_period_id.asc())
        .all()
    )
    if len(current_periods) != 1:
        raise ValueError("PayPeriod not found")
    pay_period = current_periods[0]
    payroll_run = (
        db.query(PayrollRun)
        .filter(PayrollRun.company_id == int(company_id))
        .filter(PayrollRun.pay_period_id == str(pay_period.pay_period_id))
        .one_or_none()
    )
    return pay_period, payroll_run


def _ensure_execution_context(
    *,
    db: Session,
    company_id: int,
    pay_period_id: str | None,
    payroll_run_id: str | None,
    actor_user_id: str | None,
) -> PayrollExecutionContext:
    pay_period, payroll_run = _resolve_pay_period(
        db=db,
        company_id=int(company_id),
        pay_period_id=pay_period_id,
        payroll_run_id=payroll_run_id,
    )

    run_created = False
    items_created = 0
    if payroll_run is None:
        pending_count, pending_example_ids = _pending_time_entries_for_pay_period(
            db=db,
            company_id=int(company_id),
            pay_period=pay_period,
        )
        if pending_count > 0:
            raise PayrollExecutionConflictError(
                {
                    "error": "unapproved_time_entries_exist",
                    "pending_entries_count": int(pending_count),
                    "example_time_entry_ids": pending_example_ids,
                }
            )

        payroll_run = PayrollRun(
            company_id=int(company_id),
            pay_period_id=str(pay_period.pay_period_id),
            status="DRAFT",
        )
        db.add(payroll_run)
        db.flush()
        items = build_payroll_items_for_run(
            db=db,
            company_id=int(company_id),
            payroll_run_id=str(payroll_run.payroll_run_id),
            pay_period=pay_period,
        )
        record_payroll_audit_event(
            db=db,
            company_id=int(company_id),
            payroll_run_id=str(payroll_run.payroll_run_id),
            event_type=PAYROLL_RUN_CREATED_EVENT,
            actor_user_id=actor_user_id,
            payload_json={
                "pay_period_id": str(pay_period.pay_period_id),
                "status": str(payroll_run.status),
                "items_created": int(len(items)),
                "created_via": "processing_execute",
            },
        )
        run_created = True
        items_created = len(items)

    return PayrollExecutionContext(
        pay_period=pay_period,
        payroll_run=payroll_run,
        run_created=run_created,
        items_created=items_created,
    )


def execute_payroll_run_flow(
    *,
    db: Session,
    company_id: int,
    pay_period_id: str | None,
    payroll_run_id: str | None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    context = _ensure_execution_context(
        db=db,
        company_id=int(company_id),
        pay_period_id=pay_period_id,
        payroll_run_id=payroll_run_id,
        actor_user_id=actor_user_id,
    )
    payroll_run = context.payroll_run

    if str(payroll_run.status) == "POSTED":
        overview = get_payroll_processing_overview(
            db=db,
            company_id=int(company_id),
            payroll_run_id=str(payroll_run.payroll_run_id),
            pay_period_id=None,
        )
        record_payroll_audit_event(
            db=db,
            company_id=int(company_id),
            payroll_run_id=str(payroll_run.payroll_run_id),
            event_type=PAYROLL_RUN_EXECUTED_EVENT,
            actor_user_id=actor_user_id,
            payload_json={
                "pay_period_id": str(payroll_run.pay_period_id),
                "status": str(payroll_run.status),
                "run_created": bool(context.run_created),
                "items_created": int(context.items_created),
                "finalized": False,
                "paystubs": {"generated": 0, "skipped": 0},
                "deductions": {"generated": 0, "skipped": 0},
                "pay_employees_ready": bool(overview["run_execution"]["readiness"]["pay_employees_ready"]),
            },
        )
        return {
            "payroll_run_id": str(payroll_run.payroll_run_id),
            "pay_period_id": str(payroll_run.pay_period_id),
            "status": str(payroll_run.status),
            "run_created": context.run_created,
            "items_created": int(context.items_created),
            "finalized": False,
            "paystubs": {"generated": 0, "skipped": 0},
            "deductions": {"generated": 0, "skipped": 0},
            "pay_employees_ready": bool(overview["run_execution"]["readiness"]["pay_employees_ready"]),
            "processing_overview": overview,
        }

    finalized = False
    if str(payroll_run.status) == "DRAFT":
        finalize_result = finalize_payroll_run(
            db=db,
            company_id=int(company_id),
            payroll_run_id=str(payroll_run.payroll_run_id),
            actor_user_id=actor_user_id,
        )
        finalized = True
        paystub_result = finalize_result["paystubs"]
        deduction_result = finalize_result["deductions"]
        db.flush()
    else:
        db.flush()
        paystub_result = generate_paystubs_for_run(
            company_id=int(company_id),
            payroll_run_id=str(payroll_run.payroll_run_id),
            db=db,
        )
        db.flush()
        deduction_result = generate_deductions_for_run(
            company_id=int(company_id),
            payroll_run_id=str(payroll_run.payroll_run_id),
            db=db,
        )
        db.flush()

    overview = get_payroll_processing_overview(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(payroll_run.payroll_run_id),
        pay_period_id=None,
    )

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(payroll_run.payroll_run_id),
        event_type=PAYROLL_RUN_EXECUTED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "pay_period_id": str(payroll_run.pay_period_id),
            "status": str(payroll_run.status),
            "run_created": bool(context.run_created),
            "items_created": int(context.items_created),
            "finalized": bool(finalized),
            "paystubs": {
                "generated": int(paystub_result["generated"]),
                "skipped": int(paystub_result["skipped"]),
            },
            "deductions": {
                "generated": int(deduction_result["generated"]),
                "skipped": int(deduction_result["skipped"]),
            },
            "pay_employees_ready": bool(overview["run_execution"]["readiness"]["pay_employees_ready"]),
        },
    )

    return {
        "payroll_run_id": str(payroll_run.payroll_run_id),
        "pay_period_id": str(payroll_run.pay_period_id),
        "status": str(payroll_run.status),
        "run_created": context.run_created,
        "items_created": int(context.items_created),
        "finalized": finalized,
        "paystubs": {
            "generated": int(paystub_result["generated"]),
            "skipped": int(paystub_result["skipped"]),
        },
        "deductions": {
            "generated": int(deduction_result["generated"]),
            "skipped": int(deduction_result["skipped"]),
        },
        "pay_employees_ready": bool(overview["run_execution"]["readiness"]["pay_employees_ready"]),
        "processing_overview": overview,
    }

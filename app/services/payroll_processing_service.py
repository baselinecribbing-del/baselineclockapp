from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.pay_period import PayPeriod
from app.models.payroll_deduction import PayrollDeduction
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.models.paystub import Paystub
from app.models.time_entry import TimeEntry
from app.services.payroll_readiness_summary import get_payroll_readiness_summary


def _serialize_pay_period(pay_period: PayPeriod | None) -> dict[str, Any] | None:
    if pay_period is None:
        return None
    return {
        "pay_period_id": str(pay_period.pay_period_id),
        "start_date": pay_period.start_date.isoformat(),
        "end_date": pay_period.end_date.isoformat(),
        "status": str(pay_period.status),
    }


def _serialize_payroll_run(payroll_run: PayrollRun | None) -> dict[str, Any] | None:
    if payroll_run is None:
        return None
    return {
        "payroll_run_id": str(payroll_run.payroll_run_id),
        "company_id": int(payroll_run.company_id),
        "pay_period_id": str(payroll_run.pay_period_id),
        "status": str(payroll_run.status),
        "created_at": None if payroll_run.created_at is None else payroll_run.created_at.isoformat(),
        "posted_at": None if payroll_run.posted_at is None else payroll_run.posted_at.isoformat(),
    }


def _decimal_to_float(value: Decimal | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _resolve_context(
    *,
    db: Session,
    company_id: int,
    payroll_run_id: str | None,
    pay_period_id: str | None,
) -> tuple[PayPeriod | None, PayrollRun | None]:
    payroll_run: PayrollRun | None = None
    pay_period: PayPeriod | None = None

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
    if len(current_periods) == 1:
        pay_period = current_periods[0]
        payroll_run = (
            db.query(PayrollRun)
            .filter(PayrollRun.company_id == int(company_id))
            .filter(PayrollRun.pay_period_id == str(pay_period.pay_period_id))
            .one_or_none()
        )
    return pay_period, payroll_run


def _approved_hours_review_for_period(*, db: Session, company_id: int, pay_period: PayPeriod | None) -> dict[str, Any]:
    if pay_period is None:
        return {"total_approved_hours": 0.0, "rows": []}

    entries = (
        db.query(Employee.id, Employee.name, TimeEntry.started_at, TimeEntry.ended_at)
        .join(TimeEntry, (TimeEntry.employee_id == Employee.id) & (TimeEntry.company_id == Employee.company_id))
        .filter(Employee.company_id == int(company_id))
        .filter(Employee.requires_payroll.is_(True))
        .filter(TimeEntry.status == "completed")
        .filter(TimeEntry.approval_status == "approved")
        .filter(func.date(TimeEntry.started_at) >= pay_period.start_date)
        .filter(func.date(TimeEntry.started_at) <= pay_period.end_date)
        .filter(
            ~TimeEntry.time_entry_id.in_(
                select(PayrollItem.source_time_entry_id)
                .where(PayrollItem.company_id == int(company_id))
                .where(PayrollItem.source_time_entry_id.isnot(None))
            )
        )
        .order_by(Employee.name.asc(), Employee.id.asc(), TimeEntry.started_at.asc())
        .all()
    )

    grouped: dict[int, dict[str, Any]] = {}
    for employee_id, employee_name, started_at, ended_at in entries:
        if ended_at is None:
            continue
        row = grouped.setdefault(
            int(employee_id),
            {
                "employee_id": int(employee_id),
                "employee_name": str(employee_name),
                "approved_hours": 0.0,
                "approved_entry_count": 0,
            },
        )
        row["approved_hours"] = round(
            float(row["approved_hours"]) + ((ended_at - started_at).total_seconds() / 3600.0),
            2,
        )
        row["approved_entry_count"] = int(row["approved_entry_count"]) + 1

    serialized_rows = list(grouped.values())
    total_approved_hours = 0.0
    for row in serialized_rows:
        total_approved_hours += float(row["approved_hours"])

    return {
        "total_approved_hours": round(total_approved_hours, 2),
        "rows": serialized_rows,
    }


def _approved_hours_review_for_run(*, db: Session, company_id: int, payroll_run_id: str) -> dict[str, Any]:
    rows = (
        db.query(
            Employee.id,
            Employee.name,
            func.coalesce(func.sum(PayrollItem.hours), 0),
            func.count(PayrollItem.id),
            func.coalesce(func.sum(PayrollItem.gross_pay_cents), 0),
        )
        .join(
            PayrollItem,
            (PayrollItem.employee_id == Employee.id) & (PayrollItem.company_id == Employee.company_id),
        )
        .filter(Employee.company_id == int(company_id))
        .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
        .group_by(Employee.id, Employee.name)
        .order_by(Employee.name.asc(), Employee.id.asc())
        .all()
    )
    return {
        "total_approved_hours": round(sum(_decimal_to_float(row[2]) for row in rows), 2),
        "rows": [
            {
                "employee_id": int(employee_id),
                "employee_name": str(employee_name),
                "approved_hours": round(_decimal_to_float(hours_value), 2),
                "approved_entry_count": int(item_count or 0),
                "gross_pay_cents": int(gross_pay_cents or 0),
            }
            for employee_id, employee_name, hours_value, item_count, gross_pay_cents in rows
        ],
    }


def _pay_employees_dataset(*, db: Session, company_id: int, payroll_run: PayrollRun | None) -> dict[str, Any]:
    if payroll_run is None:
        return {
            "rows": [],
            "gross_total_cents": 0,
            "total_net_payroll_cents": None,
            "deductions_ready": False,
        }

    item_totals = {
        int(employee_id): int(gross_pay_cents or 0)
        for employee_id, gross_pay_cents in (
            db.query(
                PayrollItem.employee_id,
                func.coalesce(func.sum(PayrollItem.gross_pay_cents), 0),
            )
            .filter(PayrollItem.company_id == int(company_id))
            .filter(PayrollItem.payroll_run_id == str(payroll_run.payroll_run_id))
            .group_by(PayrollItem.employee_id)
            .all()
        )
    }

    paystubs = (
        db.query(Paystub)
        .filter(Paystub.company_id == int(company_id))
        .filter(Paystub.payroll_run_id == str(payroll_run.payroll_run_id))
        .order_by(Paystub.employee_id.asc(), Paystub.paystub_id.asc())
        .all()
    )
    paystub_by_employee = {int(row.employee_id): row for row in paystubs}

    deduction_counts = {
        int(employee_id): int(count or 0)
        for employee_id, count in (
            db.query(PayrollDeduction.employee_id, func.count(PayrollDeduction.deduction_id))
            .filter(PayrollDeduction.company_id == int(company_id))
            .filter(PayrollDeduction.payroll_run_id == str(payroll_run.payroll_run_id))
            .filter(PayrollDeduction.paystub_id.isnot(None))
            .group_by(PayrollDeduction.employee_id)
            .all()
        )
    }
    deduction_totals = {
        int(employee_id): int(amount_cents or 0)
        for employee_id, amount_cents in (
            db.query(
                PayrollDeduction.employee_id,
                func.coalesce(func.sum(PayrollDeduction.amount_cents), 0),
            )
            .filter(PayrollDeduction.company_id == int(company_id))
            .filter(PayrollDeduction.payroll_run_id == str(payroll_run.payroll_run_id))
            .filter(PayrollDeduction.paystub_id.isnot(None))
            .group_by(PayrollDeduction.employee_id)
            .all()
        )
    }
    deductions_ready = bool(deduction_counts)

    employees = (
        db.query(Employee)
        .filter(Employee.company_id == int(company_id))
        .filter(Employee.id.in_(list(item_totals.keys()) or [-1]))
        .order_by(Employee.name.asc(), Employee.id.asc())
        .all()
    )

    rows: list[dict[str, Any]] = []
    total_net_payroll_cents = 0 if deductions_ready else None
    for employee in employees:
        gross_pay_cents = int(item_totals.get(int(employee.id), 0))
        paystub = paystub_by_employee.get(int(employee.id))
        deductions_cents = None
        net_pay_cents = None
        if deductions_ready:
            deductions_cents = int(deduction_totals.get(int(employee.id), 0))
            net_pay_cents = int(gross_pay_cents) - deductions_cents
            if total_net_payroll_cents is not None:
                total_net_payroll_cents += net_pay_cents

        rows.append(
            {
                "employee_id": int(employee.id),
                "employee": {
                    "id": int(employee.id),
                    "name": str(employee.name),
                },
                "gross_pay_cents": gross_pay_cents,
                "deductions_cents": deductions_cents,
                "net_pay_cents": net_pay_cents,
                "payment_method": employee.payment_method,
                "paystub_id": None if paystub is None else str(paystub.paystub_id),
                "deductions_row_count": int(deduction_counts.get(int(employee.id), 0)),
            }
        )

    return {
        "rows": rows,
        "gross_total_cents": int(sum(item_totals.values())),
        "total_net_payroll_cents": total_net_payroll_cents,
        "deductions_ready": deductions_ready,
    }


def _run_execution_state(*, db: Session, company_id: int, payroll_run: PayrollRun | None, readiness: dict[str, Any], pay_employees: dict[str, Any]) -> dict[str, Any]:
    if payroll_run is None:
        return {
            "payroll_run": None,
            "approval_state": {
                "time_entry_approval_status": "READY" if int(readiness["pending_time_approvals_count"]) == 0 else "BLOCKED",
                "payroll_run_status": None,
            },
            "counts": {
                "payroll_items": 0,
                "paystubs": 0,
                "payroll_deductions": 0,
            },
            "readiness": {
                "approved_hours_ready": bool(int(readiness["pending_time_approvals_count"]) == 0),
                "payroll_run_ready": False,
                "paystubs_ready": False,
                "deductions_ready": False,
                "pay_employees_ready": False,
            },
        }

    item_count = int(
        db.query(func.count(PayrollItem.id))
        .filter(PayrollItem.company_id == int(company_id))
        .filter(PayrollItem.payroll_run_id == str(payroll_run.payroll_run_id))
        .scalar()
        or 0
    )
    paystub_count = int(
        db.query(func.count(Paystub.paystub_id))
        .filter(Paystub.company_id == int(company_id))
        .filter(Paystub.payroll_run_id == str(payroll_run.payroll_run_id))
        .scalar()
        or 0
    )
    deduction_count = int(
        db.query(func.count(PayrollDeduction.deduction_id))
        .filter(PayrollDeduction.company_id == int(company_id))
        .filter(PayrollDeduction.payroll_run_id == str(payroll_run.payroll_run_id))
        .scalar()
        or 0
    )

    employee_row_count = int(len(pay_employees["rows"]))
    paystubs_ready = employee_row_count > 0 and paystub_count >= employee_row_count
    deductions_ready = bool(pay_employees["deductions_ready"])

    return {
        "payroll_run": _serialize_payroll_run(payroll_run),
        "approval_state": {
            "time_entry_approval_status": "READY" if int(readiness["pending_time_approvals_count"]) == 0 else "BLOCKED",
            "payroll_run_status": str(payroll_run.status),
        },
        "counts": {
            "payroll_items": item_count,
            "paystubs": paystub_count,
            "payroll_deductions": deduction_count,
        },
        "readiness": {
            "approved_hours_ready": bool(int(readiness["pending_time_approvals_count"]) == 0),
            "payroll_run_ready": True,
            "paystubs_ready": paystubs_ready,
            "deductions_ready": deductions_ready,
            "pay_employees_ready": bool(
                employee_row_count > 0
                and paystubs_ready
                and deductions_ready
                and pay_employees["total_net_payroll_cents"] is not None
            ),
        },
    }


def get_payroll_processing_overview(
    *,
    db: Session,
    company_id: int,
    payroll_run_id: str | None,
    pay_period_id: str | None,
) -> dict[str, Any]:
    pay_period, payroll_run = _resolve_context(
        db=db,
        company_id=int(company_id),
        payroll_run_id=payroll_run_id,
        pay_period_id=pay_period_id,
    )

    readiness = get_payroll_readiness_summary(db=db, company_id=int(company_id))
    pay_employees = _pay_employees_dataset(
        db=db,
        company_id=int(company_id),
        payroll_run=payroll_run,
    )

    run_creation = {
        "existing_payroll_run_id": None if payroll_run is None else str(payroll_run.payroll_run_id),
        "can_create_payroll_run": payroll_run is None and pay_period is not None,
        "blocking_issues": {
            "pending_time_approvals_count": int(readiness["pending_time_approvals_count"]),
            "rejected_time_entries_count": int(readiness["rejected_time_entries_count"]),
        },
    }

    run_execution = _run_execution_state(
        db=db,
        company_id=int(company_id),
        payroll_run=payroll_run,
        readiness=readiness,
        pay_employees=pay_employees,
    )

    approved_hours_review = (
        _approved_hours_review_for_run(
            db=db,
            company_id=int(company_id),
            payroll_run_id=str(payroll_run.payroll_run_id),
        )
        if payroll_run is not None
        else _approved_hours_review_for_period(
            db=db,
            company_id=int(company_id),
            pay_period=pay_period,
        )
    )

    return {
        "pay_period": _serialize_pay_period(pay_period),
        "approval_state": readiness,
        "run_creation": run_creation,
        "run_execution": run_execution,
        "approved_hours_review": approved_hours_review,
        "pay_employees": pay_employees,
    }

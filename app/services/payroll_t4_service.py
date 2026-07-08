from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.payroll_deduction import PayrollDeduction
from app.models.payroll_run import PayrollRun
from app.models.payroll_t4 import PayrollT4
from app.models.paystub import Paystub
from app.services.payroll_audit_service import (
    PAYROLL_T4_MARKED_DELIVERED_MANUAL_EVENT,
    record_payroll_audit_event,
)
from app.services.payroll_t4_output_service import invalidate_t4_slip, mark_t4_delivered_manually
from app.services.payroll_t4_storage_service import load_t4_slip_artifact

FEDERAL_TAX_CODES = {"TAX", "FEDERAL_TAX", "FED_TAX_OVERRIDE"}
PROVINCIAL_TAX_CODES = {"PROVINCIAL_TAX", "PROV_TAX_OVERRIDE"}
INCOME_TAX_CODES = FEDERAL_TAX_CODES | PROVINCIAL_TAX_CODES


@dataclass(frozen=True)
class PayrollT4ListRecord:
    t4_id: str
    company_id: int
    employee_id: int
    employee_name: str | None
    tax_year: int
    employment_income_cents: int
    cpp_contributions_cents: int
    ei_premiums_cents: int
    income_tax_deducted_cents: int
    other_deductions_cents: int
    slip_status: str
    slip_storage_key: str | None
    slip_file_name: str | None
    slip_content_type: str | None
    slip_byte_size: int | None
    slip_generated_at: datetime | None
    slip_generated_by_user_id: str | None
    slip_available_at: datetime | None
    delivery_status: str
    delivered_at: datetime | None
    delivered_by_user_id: str | None
    slip_download_count: int
    slip_last_downloaded_at: datetime | None
    slip_last_downloaded_by_user_id: str | None
    employee_download_count: int
    employee_first_downloaded_at: datetime | None
    employee_last_downloaded_at: datetime | None
    employee_last_downloaded_by_user_id: str | None
    employee_acknowledged_at: datetime | None
    employee_acknowledged_by_user_id: str | None
    generated_at: datetime
    generated_by_user_id: str | None


def _tax_year_bounds(tax_year: int) -> tuple[datetime, datetime]:
    return (
        datetime(int(tax_year), 1, 1, tzinfo=timezone.utc),
        datetime(int(tax_year) + 1, 1, 1, tzinfo=timezone.utc),
    )


def generate_t4s_for_tax_year(*, db: Session, company_id: int, tax_year: int, actor_user_id: str | None) -> dict[str, int]:
    year_start, year_end = _tax_year_bounds(int(tax_year))

    paystub_totals = (
        db.query(
            Paystub.employee_id.label("employee_id"),
            func.coalesce(func.sum(Paystub.gross_pay_cents), 0).label("employment_income_cents"),
        )
        .join(
            PayrollRun,
            (PayrollRun.company_id == Paystub.company_id) & (PayrollRun.payroll_run_id == Paystub.payroll_run_id),
        )
        .filter(Paystub.company_id == int(company_id))
        .filter(PayrollRun.status == "POSTED")
        .filter(PayrollRun.posted_at.isnot(None))
        .filter(PayrollRun.posted_at >= year_start)
        .filter(PayrollRun.posted_at < year_end)
        .group_by(Paystub.employee_id)
        .order_by(Paystub.employee_id.asc())
        .all()
    )

    deduction_rows = (
        db.query(
            PayrollDeduction.employee_id.label("employee_id"),
            PayrollDeduction.deduction_type.label("deduction_type"),
            func.coalesce(func.sum(PayrollDeduction.amount_cents), 0).label("amount_cents"),
        )
        .join(
            PayrollRun,
            (PayrollRun.company_id == PayrollDeduction.company_id)
            & (PayrollRun.payroll_run_id == PayrollDeduction.payroll_run_id),
        )
        .filter(PayrollDeduction.company_id == int(company_id))
        .filter(PayrollRun.status == "POSTED")
        .filter(PayrollRun.posted_at.isnot(None))
        .filter(PayrollRun.posted_at >= year_start)
        .filter(PayrollRun.posted_at < year_end)
        .group_by(PayrollDeduction.employee_id, PayrollDeduction.deduction_type)
        .all()
    )

    deduction_totals_by_employee: dict[int, dict[str, int]] = {}
    for row in deduction_rows:
        employee_deductions = deduction_totals_by_employee.setdefault(int(row.employee_id), {})
        employee_deductions[str(row.deduction_type)] = int(row.amount_cents or 0)

    existing_rows = (
        db.query(PayrollT4)
        .filter(PayrollT4.company_id == int(company_id))
        .filter(PayrollT4.tax_year == int(tax_year))
        .all()
    )
    existing_by_employee = {int(row.employee_id): row for row in existing_rows}

    generated = 0
    updated = 0
    source_payroll_runs = int(
        db.query(func.count(PayrollRun.payroll_run_id))
        .filter(PayrollRun.company_id == int(company_id))
        .filter(PayrollRun.status == "POSTED")
        .filter(PayrollRun.posted_at.isnot(None))
        .filter(PayrollRun.posted_at >= year_start)
        .filter(PayrollRun.posted_at < year_end)
        .scalar()
        or 0
    )

    for row in paystub_totals:
        employee_id = int(row.employee_id)
        employment_income_cents = int(row.employment_income_cents or 0)
        deductions = deduction_totals_by_employee.get(employee_id, {})

        cpp_contributions_cents = int(deductions.get("CPP", 0))
        ei_premiums_cents = int(deductions.get("EI", 0))
        income_tax_deducted_cents = sum(int(amount) for code, amount in deductions.items() if code in INCOME_TAX_CODES)
        total_deductions_cents = sum(int(amount) for amount in deductions.values())
        other_deductions_cents = max(
            0,
            total_deductions_cents - cpp_contributions_cents - ei_premiums_cents - income_tax_deducted_cents,
        )

        payroll_t4 = existing_by_employee.get(employee_id)
        if payroll_t4 is None:
            payroll_t4 = PayrollT4(
                company_id=int(company_id),
                employee_id=employee_id,
                tax_year=int(tax_year),
            )
            db.add(payroll_t4)
            generated += 1
        else:
            updated += 1
            if (
                int(payroll_t4.employment_income_cents or 0) != employment_income_cents
                or int(payroll_t4.cpp_contributions_cents or 0) != cpp_contributions_cents
                or int(payroll_t4.ei_premiums_cents or 0) != ei_premiums_cents
                or int(payroll_t4.income_tax_deducted_cents or 0) != income_tax_deducted_cents
                or int(payroll_t4.other_deductions_cents or 0) != other_deductions_cents
            ):
                invalidate_t4_slip(payroll_t4)

        payroll_t4.employment_income_cents = employment_income_cents
        payroll_t4.cpp_contributions_cents = cpp_contributions_cents
        payroll_t4.ei_premiums_cents = ei_premiums_cents
        payroll_t4.income_tax_deducted_cents = income_tax_deducted_cents
        payroll_t4.other_deductions_cents = other_deductions_cents
        payroll_t4.generated_at = datetime.now(timezone.utc)
        payroll_t4.generated_by_user_id = actor_user_id

    return {
        "tax_year": int(tax_year),
        "generated": generated,
        "updated": updated,
        "source_payroll_runs": source_payroll_runs,
    }


def list_payroll_t4s(
    *,
    db: Session,
    company_id: int,
    employee_id: int | None = None,
    tax_year: int | None = None,
    delivery_status: str | None = None,
) -> list[PayrollT4ListRecord]:
    query = (
        db.query(PayrollT4, Employee)
        .join(
            Employee,
            (Employee.company_id == PayrollT4.company_id) & (Employee.id == PayrollT4.employee_id),
        )
        .filter(PayrollT4.company_id == int(company_id))
    )
    if employee_id is not None:
        query = query.filter(PayrollT4.employee_id == int(employee_id))
    if tax_year is not None:
        query = query.filter(PayrollT4.tax_year == int(tax_year))
    if delivery_status is not None:
        query = query.filter(PayrollT4.delivery_status == str(delivery_status))

    rows = query.order_by(PayrollT4.tax_year.desc(), PayrollT4.employee_id.asc(), PayrollT4.t4_id.asc()).all()
    return [
        PayrollT4ListRecord(
            t4_id=str(payroll_t4.t4_id),
            company_id=int(payroll_t4.company_id),
            employee_id=int(payroll_t4.employee_id),
            employee_name=None if employee is None else str(employee.name),
            tax_year=int(payroll_t4.tax_year),
            employment_income_cents=int(payroll_t4.employment_income_cents),
            cpp_contributions_cents=int(payroll_t4.cpp_contributions_cents),
            ei_premiums_cents=int(payroll_t4.ei_premiums_cents),
            income_tax_deducted_cents=int(payroll_t4.income_tax_deducted_cents),
            other_deductions_cents=int(payroll_t4.other_deductions_cents),
            slip_status=str(payroll_t4.slip_status),
            slip_storage_key=payroll_t4.slip_storage_key,
            slip_file_name=payroll_t4.slip_file_name,
            slip_content_type=payroll_t4.slip_content_type,
            slip_byte_size=None if payroll_t4.slip_byte_size is None else int(payroll_t4.slip_byte_size),
            slip_generated_at=payroll_t4.slip_generated_at,
            slip_generated_by_user_id=payroll_t4.slip_generated_by_user_id,
            slip_available_at=payroll_t4.slip_available_at,
            delivery_status=str(payroll_t4.delivery_status),
            delivered_at=payroll_t4.delivered_at,
            delivered_by_user_id=payroll_t4.delivered_by_user_id,
            slip_download_count=int(payroll_t4.slip_download_count or 0),
            slip_last_downloaded_at=payroll_t4.slip_last_downloaded_at,
            slip_last_downloaded_by_user_id=payroll_t4.slip_last_downloaded_by_user_id,
            employee_download_count=int(payroll_t4.employee_download_count or 0),
            employee_first_downloaded_at=payroll_t4.employee_first_downloaded_at,
            employee_last_downloaded_at=payroll_t4.employee_last_downloaded_at,
            employee_last_downloaded_by_user_id=payroll_t4.employee_last_downloaded_by_user_id,
            employee_acknowledged_at=payroll_t4.employee_acknowledged_at,
            employee_acknowledged_by_user_id=payroll_t4.employee_acknowledged_by_user_id,
            generated_at=payroll_t4.generated_at,
            generated_by_user_id=payroll_t4.generated_by_user_id,
        )
        for payroll_t4, employee in rows
    ]


def get_company_payroll_t4(*, db: Session, company_id: int, t4_id: str) -> PayrollT4 | None:
    return (
        db.query(PayrollT4)
        .filter(PayrollT4.company_id == int(company_id))
        .filter(PayrollT4.t4_id == str(t4_id))
        .one_or_none()
    )


def mark_payroll_t4_delivered_manual(
    *,
    db: Session,
    company_id: int,
    t4_id: str,
    actor_user_id: str | None,
) -> tuple[PayrollT4, bool]:
    row = get_company_payroll_t4(db=db, company_id=int(company_id), t4_id=str(t4_id))
    if row is None:
        raise ValueError("T4 record not found")
    if str(row.slip_status) != "AVAILABLE" or load_t4_slip_artifact(row) is None:
        raise ValueError("T4 slip is not available")
    if str(row.delivery_status) == "DELIVERED_MANUAL":
        return row, False

    mark_t4_delivered_manually(row, actor_user_id=actor_user_id)
    db.flush()
    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=PAYROLL_T4_MARKED_DELIVERED_MANUAL_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "t4_id": str(row.t4_id),
            "employee_id": int(row.employee_id),
            "tax_year": int(row.tax_year),
            "delivery_status": str(row.delivery_status),
            "delivered_at": None if row.delivered_at is None else row.delivered_at.isoformat(),
            "delivered_by_user_id": row.delivered_by_user_id,
        },
    )
    return row, True

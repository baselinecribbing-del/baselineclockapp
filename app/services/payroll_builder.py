from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.time_entry import TimeEntry


def _decimal_hours(entry: TimeEntry) -> Decimal:
    seconds = Decimal((entry.ended_at - entry.started_at).total_seconds())
    hours = seconds / Decimal("3600")
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_payroll_items_for_run(
    db: Session,
    company_id: int,
    payroll_run_id: str,
    pay_period: PayPeriod,
) -> list[PayrollItem]:
    existing = (
        db.query(PayrollItem)
        .filter(PayrollItem.company_id == int(company_id))
        .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
        .count()
    )
    if existing:
        return []

    entries = (
        db.query(TimeEntry)
        .filter(TimeEntry.company_id == int(company_id))
        .filter(TimeEntry.status == "completed")
        .filter(TimeEntry.approval_status == "approved")
        .filter(func.date(TimeEntry.started_at) >= pay_period.start_date)
        .filter(func.date(TimeEntry.started_at) <= pay_period.end_date)
        .order_by(TimeEntry.employee_id.asc(), TimeEntry.started_at.asc())
        .all()
    )

    items: list[PayrollItem] = []

    for entry in entries:
        if entry.ended_at is None:
            continue

        employee = (
            db.query(Employee)
            .filter(Employee.company_id == int(company_id))
            .filter(Employee.id == int(entry.employee_id))
            .first()
        )
        if employee is None:
            continue

        hours = _decimal_hours(entry)
        rate_cents = int(employee.hourly_rate_cents or 0)
        gross_pay_cents = int((hours * Decimal(rate_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

        item = PayrollItem(
            company_id=int(company_id),
            payroll_run_id=str(payroll_run_id),
            employee_id=int(entry.employee_id),
            hours=hours,
            rate_cents=rate_cents,
            gross_pay_cents=gross_pay_cents,
            meta={
                "time_entry_id": entry.time_entry_id,
                "job_id": entry.job_id,
                "scope_id": entry.scope_id,
            },
        )
        db.add(item)
        items.append(item)

    return items

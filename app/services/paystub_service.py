from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.models.paystub import Paystub


def generate_paystubs_for_run(*, company_id: int, payroll_run_id: str, db: Session) -> dict:
    payroll_run = (
        db.query(PayrollRun)
        .filter(PayrollRun.company_id == int(company_id))
        .filter(PayrollRun.payroll_run_id == str(payroll_run_id))
        .one_or_none()
    )
    if payroll_run is None:
        raise ValueError("PayrollRun not found")

    if payroll_run.status == "POSTED":
        raise ValueError("Payroll run is POSTED and immutable; paystubs cannot be regenerated")
    if payroll_run.status != "FINALIZED":
        raise ValueError("Payroll run must be FINALIZED before generating paystubs")

    totals = (
        db.query(
            PayrollItem.employee_id.label("employee_id"),
            func.coalesce(func.sum(PayrollItem.gross_pay_cents), 0).label("gross_pay_cents"),
        )
        .filter(PayrollItem.company_id == int(company_id))
        .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
        .group_by(PayrollItem.employee_id)
        .order_by(PayrollItem.employee_id.asc())
        .all()
    )

    existing_employee_ids = {
        int(row.employee_id)
        for row in db.query(Paystub.employee_id)
        .filter(Paystub.company_id == int(company_id))
        .filter(Paystub.payroll_run_id == str(payroll_run_id))
        .all()
    }

    generated = 0
    skipped = 0
    for row in totals:
        employee_id = int(row.employee_id)
        gross_pay_cents = int(row.gross_pay_cents or 0)

        if employee_id in existing_employee_ids:
            skipped += 1
            continue

        db.add(
            Paystub(
                company_id=int(company_id),
                payroll_run_id=str(payroll_run_id),
                employee_id=employee_id,
                gross_pay_cents=gross_pay_cents,
                total_deductions_cents=0,
                net_pay_cents=gross_pay_cents,
            )
        )
        generated += 1

    return {
        "payroll_run_id": str(payroll_run_id),
        "generated": generated,
        "skipped": skipped,
    }

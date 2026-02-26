from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.payroll_item import PayrollItem
from app.models.job_cost_ledger import JobCostLedger


def reconcile_payroll_run_labor(
    *, company_id: int, payroll_run_id: str, db: Session
) -> dict:
    """
    Enforce invariant:
    SUM(payroll_items.gross_pay_cents)
    ==
    SUM(job_cost_ledger.total_cost_cents)
    for payroll_run_labor entries.
    """

    payroll_total = (
        db.query(func.coalesce(func.sum(PayrollItem.gross_pay_cents), 0))
        .filter(PayrollItem.company_id == int(company_id))
        .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
        .scalar()
    )

    ledger_total = (
        db.query(func.coalesce(func.sum(JobCostLedger.total_cost_cents), 0))
        .filter(JobCostLedger.company_id == int(company_id))
        .filter(JobCostLedger.source_type == "payroll_run_labor")
        .filter(JobCostLedger.source_reference_id.like(f"{payroll_run_id}:%"))
        .scalar()
    )

    payroll_total = int(payroll_total or 0)
    ledger_total = int(ledger_total or 0)

    if payroll_total != ledger_total:
        raise ValueError(
            f"Payroll reconciliation failed: payroll_total={payroll_total}, ledger_total={ledger_total}"
        )

    return {
        "payroll_total_cents": payroll_total,
        "ledger_total_cents": ledger_total,
        "delta_cents": payroll_total - ledger_total,
        "ok": True,
    }

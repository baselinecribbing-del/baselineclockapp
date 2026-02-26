import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.job_cost_ledger import JobCostLedger
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def post_labor_costs(company_id: int, payroll_run_id: str, db: Session) -> dict:
    """
    Create JobCostLedger rows from PayrollItem rows for a posted payroll run.

    Rules:
    - DO NOT commit here (outbox processor owns transaction boundaries).
    - Idempotent via unique key:
      (company_id, source_type, source_reference_id, cost_category)
    """

    posted = 0
    skipped = 0

    pr: Optional[PayrollRun] = (
        db.query(PayrollRun)
        .filter(PayrollRun.payroll_run_id == str(payroll_run_id))
        .one_or_none()
    )

    if pr is None or int(pr.company_id) != int(company_id):
        return {"posted": 0, "skipped": 0, "payroll_run_id": str(payroll_run_id)}

    posting_date = pr.posted_at or _utcnow()

    items = (
        db.query(PayrollItem)
        .filter(PayrollItem.company_id == int(company_id))
        .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
        .order_by(PayrollItem.id.asc())
        .all()
    )

    for item in items:
        meta: Any = item.meta or {}

        job_id: Optional[int] = None
        scope_id: Optional[int] = None

        if isinstance(meta, dict):
            v_job = meta.get("job_id")
            if v_job is not None:
                try:
                    job_id = int(v_job)
                except (TypeError, ValueError):
                    job_id = None

            v_scope = meta.get("scope_id")
            if v_scope is not None:
                try:
                    scope_id = int(v_scope)
                except (TypeError, ValueError):
                    scope_id = None

        if not job_id:
            skipped += 1
            continue

        source_type = "payroll_run_labor"
        cost_category = "labor"
        source_reference_id = f"{payroll_run_id}:{item.id}"

        existing = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == int(company_id))
            .filter(JobCostLedger.source_type == source_type)
            .filter(JobCostLedger.source_reference_id == source_reference_id)
            .filter(JobCostLedger.cost_category == cost_category)
            .one_or_none()
        )
        if existing is not None:
            skipped += 1
            continue

        ledger = JobCostLedger(
            company_id=int(company_id),
            job_id=int(job_id),
            scope_id=scope_id,
            employee_id=int(item.employee_id),
            source_type=source_type,
            source_reference_id=source_reference_id,
            cost_category=cost_category,
            quantity=item.hours,
            unit_cost_cents=item.rate_cents,
            total_cost_cents=int(item.gross_pay_cents),
            posting_date=posting_date,
        )
        db.add(ledger)
        db.flush()
        posted += 1

    return {"posted": posted, "skipped": skipped, "payroll_run_id": str(payroll_run_id)}

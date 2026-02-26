from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.job_cost_ledger import JobCostLedger


def job_cost_totals(
    *,
    company_id: int,
    date_start: datetime,
    date_end: datetime,
    db: Session,
    job_id: Optional[int] = None,
    scope_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    cost_category: Optional[str] = None,
    source_type: Optional[str] = None,
) -> dict[str, Any]:
    """
    Read-only reporting query.

    Semantics:
      posting_date >= date_start AND posting_date < date_end
    Grouping:
      job_id, scope_id, employee_id
    """

    q = (
        db.query(
            JobCostLedger.job_id.label("job_id"),
            JobCostLedger.scope_id.label("scope_id"),
            JobCostLedger.employee_id.label("employee_id"),
            func.count(JobCostLedger.id).label("row_count"),
            func.coalesce(func.sum(JobCostLedger.total_cost_cents), 0).label("total_cost_cents"),
        )
        .filter(JobCostLedger.company_id == int(company_id))
        .filter(JobCostLedger.posting_date >= date_start)
        .filter(JobCostLedger.posting_date < date_end)
    )

    if job_id is not None:
        q = q.filter(JobCostLedger.job_id == int(job_id))
    if scope_id is not None:
        q = q.filter(JobCostLedger.scope_id == int(scope_id))
    if employee_id is not None:
        q = q.filter(JobCostLedger.employee_id == int(employee_id))
    if cost_category is not None:
        q = q.filter(JobCostLedger.cost_category == str(cost_category))
    if source_type is not None:
        q = q.filter(JobCostLedger.source_type == str(source_type))

    rows = (
        q.group_by(JobCostLedger.job_id, JobCostLedger.scope_id, JobCostLedger.employee_id)
        .order_by(
            JobCostLedger.job_id.asc(),
            JobCostLedger.scope_id.asc().nullsfirst(),
            JobCostLedger.employee_id.asc().nullsfirst(),
        )
        .all()
    )

    return {
        "company_id": int(company_id),
        "date_start": date_start.isoformat(),
        "date_end": date_end.isoformat(),
        "filters": {
            "job_id": job_id,
            "scope_id": scope_id,
            "employee_id": employee_id,
            "cost_category": cost_category,
            "source_type": source_type,
        },
        "groups": [
            {
                "job_id": int(r.job_id),
                "scope_id": None if r.scope_id is None else int(r.scope_id),
                "employee_id": None if r.employee_id is None else int(r.employee_id),
                "row_count": int(r.row_count),
                "total_cost_cents": int(r.total_cost_cents),
            }
            for r in rows
        ],
    }

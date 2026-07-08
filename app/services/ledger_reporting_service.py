from __future__ import annotations

from datetime import date, datetime
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
    cost_source: Optional[str] = None,
    job_purchase_order_id: Optional[str] = None,
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
    if cost_source is not None:
        q = q.filter(JobCostLedger.cost_source == str(cost_source))
    if job_purchase_order_id is not None:
        q = q.filter(JobCostLedger.job_purchase_order_id == str(job_purchase_order_id))

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
            "cost_source": cost_source,
            "job_purchase_order_id": job_purchase_order_id,
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


def job_cost_summary_by_category_source(
    *,
    company_id: int,
    job_id: int,
    db: Session,
    scope_id: Optional[int] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
) -> dict[str, Any]:
    q = (
        db.query(
            JobCostLedger.cost_category.label("cost_category"),
            JobCostLedger.cost_source.label("cost_source"),
            func.count(JobCostLedger.id).label("row_count"),
            func.coalesce(func.sum(JobCostLedger.total_cost_cents), 0).label("total_cost_cents"),
        )
        .filter(JobCostLedger.company_id == int(company_id))
        .filter(JobCostLedger.job_id == int(job_id))
    )

    if scope_id is not None:
        q = q.filter(JobCostLedger.scope_id == int(scope_id))
    if date_start is not None:
        q = q.filter(JobCostLedger.posting_date >= date_start)
    if date_end is not None:
        q = q.filter(JobCostLedger.posting_date < date_end)

    rows = (
        q.group_by(JobCostLedger.cost_category, JobCostLedger.cost_source)
        .order_by(JobCostLedger.cost_category.asc(), JobCostLedger.cost_source.asc())
        .all()
    )

    groups = [
        {
            "cost_category": str(r.cost_category),
            "cost_source": str(r.cost_source),
            "row_count": int(r.row_count),
            "total_cost_cents": int(r.total_cost_cents),
        }
        for r in rows
    ]

    return {
        "company_id": int(company_id),
        "job_id": int(job_id),
        "scope_id": None if scope_id is None else int(scope_id),
        "date_start": None if date_start is None else date_start.isoformat(),
        "date_end": None if date_end is None else date_end.isoformat(),
        "row_count": sum(group["row_count"] for group in groups),
        "total_cost_cents": sum(group["total_cost_cents"] for group in groups),
        "groups": groups,
    }


def job_cost_daily_summary_by_category_source(
    *,
    company_id: int,
    job_id: int,
    db: Session,
    scope_id: Optional[int] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
) -> dict[str, Any]:
    posting_day = func.date(JobCostLedger.posting_date)

    q = (
        db.query(
            posting_day.label("posting_day"),
            JobCostLedger.cost_category.label("cost_category"),
            JobCostLedger.cost_source.label("cost_source"),
            func.count(JobCostLedger.id).label("row_count"),
            func.coalesce(func.sum(JobCostLedger.total_cost_cents), 0).label("total_cost_cents"),
        )
        .filter(JobCostLedger.company_id == int(company_id))
        .filter(JobCostLedger.job_id == int(job_id))
    )

    if scope_id is not None:
        q = q.filter(JobCostLedger.scope_id == int(scope_id))
    if date_start is not None:
        q = q.filter(JobCostLedger.posting_date >= date_start)
    if date_end is not None:
        q = q.filter(JobCostLedger.posting_date < date_end)

    rows = (
        q.group_by(posting_day, JobCostLedger.cost_category, JobCostLedger.cost_source)
        .order_by(posting_day.asc(), JobCostLedger.cost_category.asc(), JobCostLedger.cost_source.asc())
        .all()
    )

    groups = [
        {
            "posting_date": _iso_date(r.posting_day),
            "cost_category": str(r.cost_category),
            "cost_source": str(r.cost_source),
            "row_count": int(r.row_count),
            "total_cost_cents": int(r.total_cost_cents),
        }
        for r in rows
    ]

    return {
        "company_id": int(company_id),
        "job_id": int(job_id),
        "scope_id": None if scope_id is None else int(scope_id),
        "date_start": None if date_start is None else date_start.isoformat(),
        "date_end": None if date_end is None else date_end.isoformat(),
        "row_count": sum(group["row_count"] for group in groups),
        "total_cost_cents": sum(group["total_cost_cents"] for group in groups),
        "groups": groups,
    }


def job_cost_summary_by_source_reference(
    *,
    company_id: int,
    job_id: int,
    db: Session,
    scope_id: Optional[int] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    cost_category: Optional[str] = None,
    cost_source: Optional[str] = None,
    source_type: Optional[str] = None,
    job_purchase_order_id: Optional[str] = None,
) -> dict[str, Any]:
    q = (
        db.query(
            JobCostLedger.source_type.label("source_type"),
            JobCostLedger.source_reference_id.label("source_reference_id"),
            JobCostLedger.cost_category.label("cost_category"),
            JobCostLedger.cost_source.label("cost_source"),
            JobCostLedger.job_purchase_order_id.label("job_purchase_order_id"),
            func.count(JobCostLedger.id).label("row_count"),
            func.coalesce(func.sum(JobCostLedger.total_cost_cents), 0).label("total_cost_cents"),
        )
        .filter(JobCostLedger.company_id == int(company_id))
        .filter(JobCostLedger.job_id == int(job_id))
    )

    if scope_id is not None:
        q = q.filter(JobCostLedger.scope_id == int(scope_id))
    if date_start is not None:
        q = q.filter(JobCostLedger.posting_date >= date_start)
    if date_end is not None:
        q = q.filter(JobCostLedger.posting_date < date_end)
    if cost_category is not None:
        q = q.filter(JobCostLedger.cost_category == str(cost_category))
    if cost_source is not None:
        q = q.filter(JobCostLedger.cost_source == str(cost_source))
    if source_type is not None:
        q = q.filter(JobCostLedger.source_type == str(source_type))
    if job_purchase_order_id is not None:
        q = q.filter(JobCostLedger.job_purchase_order_id == str(job_purchase_order_id))

    rows = (
        q.group_by(
            JobCostLedger.source_type,
            JobCostLedger.source_reference_id,
            JobCostLedger.cost_category,
            JobCostLedger.cost_source,
            JobCostLedger.job_purchase_order_id,
        )
        .order_by(
            JobCostLedger.cost_category.asc(),
            JobCostLedger.cost_source.asc(),
            JobCostLedger.source_type.asc(),
            JobCostLedger.source_reference_id.asc(),
        )
        .all()
    )

    groups = [
        {
            "source_type": str(r.source_type),
            "source_reference_id": str(r.source_reference_id),
            "cost_category": str(r.cost_category),
            "cost_source": str(r.cost_source),
            "job_purchase_order_id": None if r.job_purchase_order_id is None else str(r.job_purchase_order_id),
            "row_count": int(r.row_count),
            "total_cost_cents": int(r.total_cost_cents),
        }
        for r in rows
    ]

    return {
        "company_id": int(company_id),
        "job_id": int(job_id),
        "scope_id": None if scope_id is None else int(scope_id),
        "date_start": None if date_start is None else date_start.isoformat(),
        "date_end": None if date_end is None else date_end.isoformat(),
        "filters": {
            "cost_category": cost_category,
            "cost_source": cost_source,
            "source_type": source_type,
            "job_purchase_order_id": job_purchase_order_id,
        },
        "row_count": sum(group["row_count"] for group in groups),
        "total_cost_cents": sum(group["total_cost_cents"] for group in groups),
        "groups": groups,
    }


def job_cost_summary_by_source_type(
    *,
    company_id: int,
    job_id: int,
    db: Session,
    scope_id: Optional[int] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    cost_category: Optional[str] = None,
    cost_source: Optional[str] = None,
    job_purchase_order_id: Optional[str] = None,
) -> dict[str, Any]:
    q = (
        db.query(
            JobCostLedger.source_type.label("source_type"),
            JobCostLedger.cost_category.label("cost_category"),
            JobCostLedger.cost_source.label("cost_source"),
            func.count(JobCostLedger.id).label("row_count"),
            func.coalesce(func.sum(JobCostLedger.total_cost_cents), 0).label("total_cost_cents"),
        )
        .filter(JobCostLedger.company_id == int(company_id))
        .filter(JobCostLedger.job_id == int(job_id))
    )

    if scope_id is not None:
        q = q.filter(JobCostLedger.scope_id == int(scope_id))
    if date_start is not None:
        q = q.filter(JobCostLedger.posting_date >= date_start)
    if date_end is not None:
        q = q.filter(JobCostLedger.posting_date < date_end)
    if cost_category is not None:
        q = q.filter(JobCostLedger.cost_category == str(cost_category))
    if cost_source is not None:
        q = q.filter(JobCostLedger.cost_source == str(cost_source))
    if job_purchase_order_id is not None:
        q = q.filter(JobCostLedger.job_purchase_order_id == str(job_purchase_order_id))

    rows = (
        q.group_by(
            JobCostLedger.source_type,
            JobCostLedger.cost_category,
            JobCostLedger.cost_source,
        )
        .order_by(
            JobCostLedger.cost_category.asc(),
            JobCostLedger.cost_source.asc(),
            JobCostLedger.source_type.asc(),
        )
        .all()
    )

    groups = [
        {
            "source_type": str(r.source_type),
            "cost_category": str(r.cost_category),
            "cost_source": str(r.cost_source),
            "row_count": int(r.row_count),
            "total_cost_cents": int(r.total_cost_cents),
        }
        for r in rows
    ]

    return {
        "company_id": int(company_id),
        "job_id": int(job_id),
        "scope_id": None if scope_id is None else int(scope_id),
        "date_start": None if date_start is None else date_start.isoformat(),
        "date_end": None if date_end is None else date_end.isoformat(),
        "filters": {
            "cost_category": cost_category,
            "cost_source": cost_source,
            "job_purchase_order_id": job_purchase_order_id,
        },
        "row_count": sum(group["row_count"] for group in groups),
        "total_cost_cents": sum(group["total_cost_cents"] for group in groups),
        "groups": groups,
    }


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)

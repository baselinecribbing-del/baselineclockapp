from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.job_cost_ledger import JobCostLedger
from app.models.job_purchase_order import JobPurchaseOrder


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _reference_id(job_purchase_order_id: str, description: str) -> str:
    return f"po:{job_purchase_order_id}:{description.strip()}"


def record_po_cost(
    company_id: int,
    job_purchase_order_id: str,
    amount_cents: int,
    description: str,
    *,
    db: Session,
) -> JobCostLedger:
    if int(amount_cents) < 0:
        raise ValueError("amount_cents must be nonnegative")

    desc = str(description).strip()
    if not desc:
        raise ValueError("description is required")

    po = (
        db.query(JobPurchaseOrder)
        .filter(JobPurchaseOrder.company_id == int(company_id))
        .filter(JobPurchaseOrder.job_purchase_order_id == str(job_purchase_order_id))
        .one_or_none()
    )
    if po is None:
        raise ValueError("Job purchase order not found")

    source_type = "purchase_order_cost"
    cost_category = "material"
    source_reference_id = _reference_id(str(job_purchase_order_id), desc)

    existing = (
        db.query(JobCostLedger)
        .filter(JobCostLedger.company_id == int(company_id))
        .filter(JobCostLedger.job_purchase_order_id == str(job_purchase_order_id))
        .filter(JobCostLedger.source_type == source_type)
        .filter(JobCostLedger.source_reference_id == source_reference_id)
        .filter(JobCostLedger.cost_category == cost_category)
        .one_or_none()
    )
    if existing is not None:
        return existing

    row = JobCostLedger(
        company_id=int(company_id),
        job_id=int(po.job_id),
        scope_id=None if po.scope_id is None else int(po.scope_id),
        employee_id=None,
        source_type=source_type,
        source_reference_id=source_reference_id,
        cost_category=cost_category,
        quantity=None,
        unit_cost_cents=None,
        total_cost_cents=int(amount_cents),
        posting_date=_utcnow(),
        job_purchase_order_id=str(po.job_purchase_order_id),
        cost_source="PO",
    )
    db.add(row)
    db.flush()
    return row

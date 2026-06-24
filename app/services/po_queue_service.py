from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.customer_site import CustomerSite
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.scope import Scope
from app.services.po_ops_creation_service import create_ops_for_po_ready_state


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_po(*, db: Session, company_id: int, job_purchase_order_id: str) -> JobPurchaseOrder:
    po = (
        db.query(JobPurchaseOrder)
        .filter(JobPurchaseOrder.company_id == int(company_id))
        .filter(JobPurchaseOrder.job_purchase_order_id == str(job_purchase_order_id))
        .one_or_none()
    )
    if po is None:
        raise ValueError("Job purchase order not found")
    return po


def mark_unmatched(
    *,
    db: Session,
    company_id: int,
    job_purchase_order_id: str,
    reviewed_by_user_id: str,
    review_notes: str | None = None,
) -> JobPurchaseOrder:
    po = _load_po(db=db, company_id=company_id, job_purchase_order_id=job_purchase_order_id)

    current = str(po.queue_status)
    if current in {"READY_FOR_OPS", "CLOSED"}:
        raise ValueError(f"Invalid queue status transition: {current} -> UNMATCHED")

    po.queue_status = "UNMATCHED"
    po.matched_job_id = None
    po.matched_scope_id = None
    po.matched_customer_site_id = None
    po.reviewed_by_user_id = str(reviewed_by_user_id)
    po.reviewed_at = _utcnow()
    po.review_notes = review_notes

    db.flush()
    return po


def match_to_job_scope_site(
    *,
    db: Session,
    company_id: int,
    job_purchase_order_id: str,
    matched_job_id: int,
    matched_scope_id: int | None,
    matched_customer_site_id: str,
    reviewed_by_user_id: str,
    review_notes: str | None = None,
) -> JobPurchaseOrder:
    po = _load_po(db=db, company_id=company_id, job_purchase_order_id=job_purchase_order_id)

    current = str(po.queue_status)
    if current in {"READY_FOR_OPS", "CLOSED"}:
        raise ValueError(f"Invalid queue status transition: {current} -> MATCHED")

    job = (
        db.query(Job)
        .filter(Job.company_id == int(company_id))
        .filter(Job.id == int(matched_job_id))
        .one_or_none()
    )
    if job is None:
        raise ValueError("Matched job not found")

    if matched_scope_id is not None:
        scope = (
            db.query(Scope)
            .filter(Scope.company_id == int(company_id))
            .filter(Scope.id == int(matched_scope_id))
            .one_or_none()
        )
        if scope is None:
            raise ValueError("Matched scope not found")
        if int(scope.job_id) != int(matched_job_id):
            raise ValueError("Matched scope must belong to matched job")

    site = (
        db.query(CustomerSite)
        .filter(CustomerSite.company_id == int(company_id))
        .filter(CustomerSite.customer_site_id == str(matched_customer_site_id))
        .one_or_none()
    )
    if site is None:
        raise ValueError("Matched customer site not found")

    po.queue_status = "MATCHED"
    po.matched_job_id = int(matched_job_id)
    po.matched_scope_id = None if matched_scope_id is None else int(matched_scope_id)
    po.matched_customer_site_id = str(matched_customer_site_id)
    po.reviewed_by_user_id = str(reviewed_by_user_id)
    po.reviewed_at = _utcnow()
    po.review_notes = review_notes

    db.flush()
    return po


def mark_ready_for_ops(
    *,
    db: Session,
    company_id: int,
    job_purchase_order_id: str,
    reviewed_by_user_id: str,
    review_notes: str | None = None,
) -> JobPurchaseOrder:
    po = _load_po(db=db, company_id=company_id, job_purchase_order_id=job_purchase_order_id)

    current = str(po.queue_status)
    if current == "CLOSED":
        raise ValueError("Invalid queue status transition: CLOSED -> READY_FOR_OPS")

    if po.matched_job_id is None or po.matched_customer_site_id is None:
        raise ValueError("Cannot mark ready for ops without matched job and customer site linkage")

    create_ops_for_po_ready_state(db=db, company_id=company_id, po=po)

    po.queue_status = "READY_FOR_OPS"
    po.reviewed_by_user_id = str(reviewed_by_user_id)
    po.reviewed_at = _utcnow()
    po.review_notes = review_notes

    db.flush()
    return po


def close_po_queue_item(
    *,
    db: Session,
    company_id: int,
    job_purchase_order_id: str,
    reviewed_by_user_id: str,
    review_notes: str | None = None,
) -> JobPurchaseOrder:
    po = _load_po(db=db, company_id=company_id, job_purchase_order_id=job_purchase_order_id)

    current = str(po.queue_status)
    if current == "CLOSED":
        raise ValueError("Invalid queue status transition: CLOSED -> CLOSED")

    po.queue_status = "CLOSED"
    po.reviewed_by_user_id = str(reviewed_by_user_id)
    po.reviewed_at = _utcnow()
    po.review_notes = review_notes

    db.flush()
    return po

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.bin_service_request import BinServiceRequest
from app.models.bin_service_ticket import BinServiceTicket
from app.models.customer_site import CustomerSite
from app.models.foundation_work_package import FoundationWorkPackage
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.scope import Scope


@dataclass(frozen=True)
class _OpsProfile:
    domain: str
    waste_bin_request_type: str | None


def _load_scope_for_po(*, db: Session, company_id: int, po: JobPurchaseOrder) -> Scope:
    scope_id = po.matched_scope_id if po.matched_scope_id is not None else po.scope_id
    if scope_id is None:
        raise ValueError("Unable to determine operational type: scope linkage missing")

    scope = (
        db.query(Scope)
        .filter(Scope.company_id == int(company_id))
        .filter(Scope.id == int(scope_id))
        .one_or_none()
    )
    if scope is None:
        raise ValueError("Matched scope not found")

    expected_job_id = po.matched_job_id if po.matched_job_id is not None else po.job_id
    if int(scope.job_id) != int(expected_job_id):
        raise ValueError("Matched scope must belong to matched job")

    return scope


def _infer_waste_bin_request_type(haystack: str) -> str:
    if "swap" in haystack:
        return "SWAP"
    if "pickup" in haystack or "pick up" in haystack:
        return "PICKUP"
    if "drop" in haystack or "delivery" in haystack:
        return "DROP"
    return "DROP"


def _infer_ops_profile(*, po: JobPurchaseOrder, scope: Scope) -> _OpsProfile:
    scope_name = str(scope.name or "")
    review_notes = str(po.review_notes or "")
    vendor_name = str(po.vendor_name or "")
    po_number = str(po.po_number or "")
    haystack = " ".join([scope_name, review_notes, vendor_name, po_number]).lower()

    if any(token in haystack for token in ["waste", "bin", "dumpster", "landfill", "swap", "pickup", "drop"]):
        return _OpsProfile(domain="WASTE_BIN", waste_bin_request_type=_infer_waste_bin_request_type(haystack))

    if any(token in haystack for token in ["foundation", "footing", "concrete", "rebar", "formwork"]):
        return _OpsProfile(domain="FOUNDATION", waste_bin_request_type=None)

    if any(token in haystack for token in ["electrical", "plumbing", "hvac", "painting", "drywall"]):
        raise ValueError("Unable to determine operational type from scope/PO metadata")

    return _OpsProfile(domain="WASTE_BIN", waste_bin_request_type="DROP")


def create_waste_bin_ops(
    *,
    db: Session,
    company_id: int,
    po: JobPurchaseOrder,
    request_type: str,
) -> tuple[BinServiceRequest, BinServiceTicket]:
    if po.matched_customer_site_id is None:
        raise ValueError("Cannot create waste-bin ops without matched customer site linkage")

    site = (
        db.query(CustomerSite)
        .filter(CustomerSite.company_id == int(company_id))
        .filter(CustomerSite.customer_site_id == str(po.matched_customer_site_id))
        .one_or_none()
    )
    if site is None:
        raise ValueError("Matched customer site not found")

    req = (
        db.query(BinServiceRequest)
        .filter(BinServiceRequest.company_id == int(company_id))
        .filter(BinServiceRequest.job_purchase_order_id == str(po.job_purchase_order_id))
        .filter(BinServiceRequest.request_source == "PO_READY_FOR_OPS")
        .one_or_none()
    )
    if req is None:
        req = BinServiceRequest(
            company_id=int(company_id),
            customer_site_id=str(po.matched_customer_site_id),
            job_purchase_order_id=str(po.job_purchase_order_id),
            request_source="PO_READY_FOR_OPS",
            request_type=str(request_type),
            status="OPEN",
        )
        db.add(req)
        db.flush()

    ticket = (
        db.query(BinServiceTicket)
        .filter(BinServiceTicket.company_id == int(company_id))
        .filter(BinServiceTicket.bin_service_request_id == str(req.bin_service_request_id))
        .one_or_none()
    )
    if ticket is None:
        ticket = BinServiceTicket(
            company_id=int(company_id),
            bin_service_request_id=str(req.bin_service_request_id),
            customer_site_id=str(po.matched_customer_site_id),
            job_purchase_order_id=str(po.job_purchase_order_id),
            service_type=str(request_type),
            status="OPEN",
            priority="NORMAL",
        )
        db.add(ticket)
        db.flush()

    return req, ticket


def create_foundation_ops(
    *,
    db: Session,
    company_id: int,
    po: JobPurchaseOrder,
) -> FoundationWorkPackage:
    matched_job_id = po.matched_job_id if po.matched_job_id is not None else po.job_id
    matched_scope_id = po.matched_scope_id if po.matched_scope_id is not None else po.scope_id

    if matched_scope_id is None:
        raise ValueError("Cannot create foundation ops without matched scope linkage")

    job = (
        db.query(Job)
        .filter(Job.company_id == int(company_id))
        .filter(Job.id == int(matched_job_id))
        .one_or_none()
    )
    if job is None:
        raise ValueError("Matched job not found")

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

    row = (
        db.query(FoundationWorkPackage)
        .filter(FoundationWorkPackage.company_id == int(company_id))
        .filter(FoundationWorkPackage.job_purchase_order_id == str(po.job_purchase_order_id))
        .one_or_none()
    )
    if row is not None:
        return row

    row = FoundationWorkPackage(
        company_id=int(company_id),
        job_id=int(matched_job_id),
        scope_id=int(matched_scope_id),
        job_purchase_order_id=str(po.job_purchase_order_id),
        status="READY",
    )
    db.add(row)
    db.flush()
    return row


def create_ops_for_po_ready_state(
    *,
    db: Session,
    company_id: int,
    po: JobPurchaseOrder,
) -> None:
    if int(po.company_id) != int(company_id):
        raise ValueError("Job purchase order not found")

    scope = _load_scope_for_po(db=db, company_id=company_id, po=po)
    profile = _infer_ops_profile(po=po, scope=scope)

    if profile.domain == "WASTE_BIN":
        create_waste_bin_ops(
            db=db,
            company_id=company_id,
            po=po,
            request_type=str(profile.waste_bin_request_type),
        )
        return

    if profile.domain == "FOUNDATION":
        create_foundation_ops(db=db, company_id=company_id, po=po)
        return

    raise ValueError("Unsupported operational type")

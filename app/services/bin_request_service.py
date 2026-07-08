from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.models.bin_service_request import BinServiceRequest
from app.models.customer_site import CustomerSite
from app.models.job_purchase_order import JobPurchaseOrder

RequestType = Literal["DROP", "SWAP", "PICKUP"]


_ALLOWED_REQUEST_TYPES = {"DROP", "SWAP", "PICKUP"}


def create_service_request(
    *,
    db: Session,
    company_id: int,
    customer_site_id: str | None,
    request_type: RequestType,
    request_notes: str | None,
    request_source: str = "MANUAL",
    job_purchase_order_id: str | None = None,
    requested_for: datetime | None = None,
    source_email_ingestion_event_id: str | None = None,
) -> BinServiceRequest:
    req_type = str(request_type).upper()
    if req_type not in _ALLOWED_REQUEST_TYPES:
        raise ValueError("request_type must be one of DROP, SWAP, PICKUP")
    req_source = str(request_source).upper()
    if req_source not in {"MANUAL", "EMAIL_INGESTION", "PO_READY_FOR_OPS"}:
        raise ValueError("request_source must be one of MANUAL, EMAIL_INGESTION, PO_READY_FOR_OPS")

    if customer_site_id is not None:
        site = (
            db.query(CustomerSite)
            .filter(CustomerSite.company_id == int(company_id))
            .filter(CustomerSite.customer_site_id == str(customer_site_id))
            .one_or_none()
        )
        if site is None:
            raise ValueError("Customer site not found")

    if job_purchase_order_id is not None:
        po = (
            db.query(JobPurchaseOrder)
            .filter(JobPurchaseOrder.company_id == int(company_id))
            .filter(JobPurchaseOrder.job_purchase_order_id == str(job_purchase_order_id))
            .one_or_none()
        )
        if po is None:
            raise ValueError("Job purchase order not found")

    row = BinServiceRequest(
        company_id=int(company_id),
        customer_site_id=None if customer_site_id is None else str(customer_site_id),
        job_purchase_order_id=None if job_purchase_order_id is None else str(job_purchase_order_id),
        source_email_ingestion_event_id=None
        if source_email_ingestion_event_id is None
        else str(source_email_ingestion_event_id),
        request_source=req_source,
        request_type=req_type,
        requested_for=requested_for,
        status="OPEN",
        request_notes=None if request_notes is None else str(request_notes),
    )
    db.add(row)
    db.flush()
    return row

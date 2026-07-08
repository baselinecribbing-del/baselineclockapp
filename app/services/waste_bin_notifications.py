from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.bin_asset import BinAsset
from app.models.bin_service_request import BinServiceRequest
from app.models.bin_service_ticket import BinServiceTicket
from app.models.customer_site import CustomerSite
from app.models.job_purchase_order import JobPurchaseOrder


@dataclass(frozen=True)
class RenderedMessage:
    message_type: str
    subject: str
    body: str


@dataclass(frozen=True)
class _Context:
    site: CustomerSite | None
    po: JobPurchaseOrder | None
    bin_asset: BinAsset | None


def _load_context(
    *,
    db: Session,
    company_id: int,
    customer_site_id: str | None,
    job_purchase_order_id: str | None,
    assigned_bin_asset_id: str | None = None,
) -> _Context:
    site = None
    if customer_site_id is not None:
        site = (
            db.query(CustomerSite)
            .filter(CustomerSite.company_id == int(company_id))
            .filter(CustomerSite.customer_site_id == str(customer_site_id))
            .one_or_none()
        )

    po = None
    if job_purchase_order_id is not None:
        po = (
            db.query(JobPurchaseOrder)
            .filter(JobPurchaseOrder.company_id == int(company_id))
            .filter(JobPurchaseOrder.job_purchase_order_id == str(job_purchase_order_id))
            .one_or_none()
        )

    bin_asset = None
    if assigned_bin_asset_id is not None:
        bin_asset = (
            db.query(BinAsset)
            .filter(BinAsset.company_id == int(company_id))
            .filter(BinAsset.bin_asset_id == str(assigned_bin_asset_id))
            .one_or_none()
        )

    return _Context(site=site, po=po, bin_asset=bin_asset)


def _site_name(site: CustomerSite | None) -> str:
    if site is None:
        return "Unknown Site"
    if site.site_name:
        return str(site.site_name)
    return str(site.customer_name)


def _address(site: CustomerSite | None) -> str:
    if site is None:
        return "Unknown Address"
    return ", ".join([str(site.address_line_1), str(site.city), str(site.province), str(site.postal_code)])


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return value.isoformat()


def render_request_acknowledgement(*, db: Session, company_id: int, request_row: BinServiceRequest) -> RenderedMessage:
    ctx = _load_context(
        db=db,
        company_id=company_id,
        customer_site_id=request_row.customer_site_id,
        job_purchase_order_id=request_row.job_purchase_order_id,
    )
    site_name = _site_name(ctx.site)
    address = _address(ctx.site)
    po_number = ctx.po.po_number if ctx.po is not None else "N/A"

    subject = f"Waste Bin Request Acknowledged: {request_row.request_type}"
    body = (
        f"Request type: {request_row.request_type}\n"
        f"Customer/site: {site_name}\n"
        f"Address: {address}\n"
        f"PO number: {po_number}\n"
        f"Request id: {request_row.bin_service_request_id}\n"
        f"Status: {request_row.status}"
    )
    return RenderedMessage(message_type="REQUEST_ACKNOWLEDGEMENT", subject=subject, body=body)


def render_completion_confirmation(*, db: Session, company_id: int, ticket_row: BinServiceTicket) -> RenderedMessage:
    ctx = _load_context(
        db=db,
        company_id=company_id,
        customer_site_id=ticket_row.customer_site_id,
        job_purchase_order_id=ticket_row.job_purchase_order_id,
        assigned_bin_asset_id=ticket_row.assigned_bin_asset_id,
    )
    site_name = _site_name(ctx.site)
    address = _address(ctx.site)
    po_number = ctx.po.po_number if ctx.po is not None else "N/A"
    bin_number = ctx.bin_asset.bin_number if ctx.bin_asset is not None else "N/A"

    subject = f"Waste Bin Service Completed: {ticket_row.service_type}"
    body = (
        f"Service type: {ticket_row.service_type}\n"
        f"Customer/site: {site_name}\n"
        f"Address: {address}\n"
        f"PO number: {po_number}\n"
        f"Assigned bin: {bin_number}\n"
        f"Assigned vehicle: {ticket_row.assigned_vehicle_label or 'N/A'}\n"
        f"Completed at: {_fmt_dt(ticket_row.completed_at)}\n"
        f"Ticket id: {ticket_row.bin_service_ticket_id}"
    )
    return RenderedMessage(message_type="SERVICE_COMPLETION_CONFIRMATION", subject=subject, body=body)


def render_dispatch_work_order(*, db: Session, company_id: int, ticket_row: BinServiceTicket) -> RenderedMessage:
    ctx = _load_context(
        db=db,
        company_id=company_id,
        customer_site_id=ticket_row.customer_site_id,
        job_purchase_order_id=ticket_row.job_purchase_order_id,
        assigned_bin_asset_id=ticket_row.assigned_bin_asset_id,
    )
    site_name = _site_name(ctx.site)
    address = _address(ctx.site)
    po_number = ctx.po.po_number if ctx.po is not None else "N/A"
    bin_number = ctx.bin_asset.bin_number if ctx.bin_asset is not None else "N/A"

    subject = f"Work Order: {ticket_row.service_type}"
    body = (
        f"Service type: {ticket_row.service_type}\n"
        f"Customer/site: {site_name}\n"
        f"Address: {address}\n"
        f"PO number: {po_number}\n"
        f"Scheduled date: {ticket_row.scheduled_date or 'N/A'}\n"
        f"Scheduled window: {ticket_row.scheduled_time_window or 'N/A'}\n"
        f"Assigned bin: {bin_number}\n"
        f"Assigned vehicle: {ticket_row.assigned_vehicle_label or 'N/A'}\n"
        f"Ticket id: {ticket_row.bin_service_ticket_id}"
    )
    return RenderedMessage(message_type="DISPATCH_WORK_ORDER", subject=subject, body=body)

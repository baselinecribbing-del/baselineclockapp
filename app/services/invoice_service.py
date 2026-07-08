from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.bin_service_photo import BinServicePhoto
from app.models.bin_service_ticket import BinServiceTicket
from app.models.customer_site import CustomerSite
from app.models.invoice import Invoice
from app.models.invoice_line import InvoiceLine
from app.models.job_purchase_order import JobPurchaseOrder


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _service_price_cents(service_type: str) -> int:
    key_map = {
        "DROP": "WASTE_BIN_PRICE_DROP_CENTS",
        "DROP_BIN": "WASTE_BIN_PRICE_DROP_CENTS",
        "SWAP": "WASTE_BIN_PRICE_SWAP_CENTS",
        "SWAP_BIN": "WASTE_BIN_PRICE_SWAP_CENTS",
        "PICKUP": "WASTE_BIN_PRICE_PICKUP_CENTS",
        "PICKUP_BIN": "WASTE_BIN_PRICE_PICKUP_CENTS",
    }
    key = key_map.get(str(service_type).upper())
    if key is None:
        return 0

    raw = os.getenv(key, "0").strip()
    try:
        parsed = int(raw)
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _build_billing_address(site: CustomerSite) -> str:
    return ", ".join(
        [
            str(site.address_line_1),
            str(site.city),
            str(site.province),
            str(site.postal_code),
        ]
    )


def _ensure_required_proof_exists(*, db: Session, company_id: int, ticket: BinServiceTicket) -> None:
    required_photo_by_service_type = {
        "DROP": "DROP_PROOF",
        "DROP_BIN": "DROP_PROOF",
        "SWAP": "SWAP_PROOF",
        "SWAP_BIN": "SWAP_PROOF",
        "PICKUP": "PICKUP_PROOF",
        "PICKUP_BIN": "PICKUP_PROOF",
    }
    required_photo_type = required_photo_by_service_type.get(str(ticket.service_type))
    if required_photo_type is None:
        return

    has_required_photo = (
        db.query(BinServicePhoto)
        .filter(BinServicePhoto.company_id == int(company_id))
        .filter(BinServicePhoto.bin_service_ticket_id == str(ticket.bin_service_ticket_id))
        .filter(BinServicePhoto.photo_type == required_photo_type)
        .first()
        is not None
    )
    if not has_required_photo:
        raise ValueError(f"Missing required proof photo: {required_photo_type}")


def generate_invoice_for_completed_ticket(*, company_id: int, service_ticket_id: str, db: Session) -> Invoice:
    existing = (
        db.query(Invoice)
        .filter(Invoice.company_id == int(company_id))
        .filter(Invoice.service_ticket_id == str(service_ticket_id))
        .one_or_none()
    )
    if existing is not None:
        return existing

    ticket = (
        db.query(BinServiceTicket)
        .filter(BinServiceTicket.company_id == int(company_id))
        .filter(BinServiceTicket.bin_service_ticket_id == str(service_ticket_id))
        .one_or_none()
    )
    if ticket is None:
        raise ValueError("Service ticket not found")
    if str(ticket.status) != "COMPLETED":
        raise ValueError("Service ticket must be COMPLETED before invoicing")

    _ensure_required_proof_exists(db=db, company_id=company_id, ticket=ticket)

    site = (
        db.query(CustomerSite)
        .filter(CustomerSite.company_id == int(company_id))
        .filter(CustomerSite.customer_site_id == str(ticket.customer_site_id))
        .one_or_none()
    )
    if site is None:
        raise ValueError("Customer site not found")

    po_number: str | None = None
    if ticket.job_purchase_order_id is not None:
        po = (
            db.query(JobPurchaseOrder)
            .filter(JobPurchaseOrder.company_id == int(company_id))
            .filter(JobPurchaseOrder.job_purchase_order_id == str(ticket.job_purchase_order_id))
            .one_or_none()
        )
        if po is not None:
            po_number = po.po_number

    service_dt = (ticket.completed_at or _utcnow()).date()
    invoice_dt = _utcnow().date()

    service_price_cents = _service_price_cents(str(ticket.service_type))
    subtotal_cents = int(service_price_cents)
    tax_cents = 0
    total_cents = subtotal_cents + tax_cents

    site_address = _build_billing_address(site)
    builder_name = str(site.customer_name)
    line_description = (
        f"{ticket.service_type} service on {service_dt.isoformat()} | "
        f"site={site_address} | builder={builder_name} | po={po_number or 'N/A'}"
    )

    invoice = Invoice(
        company_id=int(company_id),
        customer_name=builder_name,
        customer_site_id=str(site.customer_site_id),
        job_purchase_order_id=ticket.job_purchase_order_id,
        service_ticket_id=str(ticket.bin_service_ticket_id),
        invoice_date=invoice_dt,
        service_date=service_dt,
        po_number=po_number,
        billing_address=site_address,
        status="DRAFT",
        subtotal_cents=subtotal_cents,
        tax_cents=tax_cents,
        total_cents=total_cents,
    )
    db.add(invoice)
    db.flush()

    db.add(
        InvoiceLine(
            invoice_id=str(invoice.invoice_id),
            line_type="SERVICE",
            description=line_description,
            quantity=Decimal("1.00"),
            unit_price_cents=service_price_cents,
            line_total_cents=service_price_cents,
        )
    )
    db.flush()

    return invoice

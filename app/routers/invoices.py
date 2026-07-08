from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.deps.access_control import require_operations_permission
from app.deps.auth import require_auth
from app.deps.entitlements import require_company_module
from app.models.event_outbox import EventOutbox
from app.models.invoice import Invoice
from app.models.invoice_line import InvoiceLine
from app.schemas.invoice import InvoiceLineResponse, InvoiceResponse
from app.services.access_control_service import PrivilegedPermission

router = APIRouter(prefix="/invoices", tags=["Invoices"], dependencies=[Depends(require_company_module("invoices"))])


def _ensure_company(request: Request, x_company_id: int) -> int:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")
    return int(request.state.company_id)


def _serialize_invoice(row: Invoice, lines: list[InvoiceLine]) -> InvoiceResponse:
    return InvoiceResponse(
        invoice_id=str(row.invoice_id),
        company_id=int(row.company_id),
        customer_name=str(row.customer_name),
        customer_site_id=str(row.customer_site_id),
        job_purchase_order_id=row.job_purchase_order_id,
        service_ticket_id=str(row.service_ticket_id),
        invoice_date=row.invoice_date,
        service_date=row.service_date,
        po_number=row.po_number,
        billing_address=str(row.billing_address),
        status=str(row.status),
        subtotal_cents=int(row.subtotal_cents),
        tax_cents=int(row.tax_cents),
        total_cents=int(row.total_cents),
        created_at=row.created_at,
        lines=[
            InvoiceLineResponse(
                invoice_line_id=str(line.invoice_line_id),
                invoice_id=str(line.invoice_id),
                line_type=str(line.line_type),
                description=str(line.description),
                quantity=float(line.quantity),
                unit_price_cents=int(line.unit_price_cents),
                line_total_cents=int(line.line_total_cents),
            )
            for line in lines
        ],
    )


@router.get("", response_model=list[InvoiceResponse])
def list_invoices(
    request: Request,
    status: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _permission=Depends(require_operations_permission(PrivilegedPermission.INVOICES_VIEW)),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        q = db.query(Invoice).filter(Invoice.company_id == company_id)
        if status is not None:
            q = q.filter(Invoice.status == str(status))

        rows = q.order_by(Invoice.created_at.desc(), Invoice.invoice_id.asc()).all()
        if not rows:
            return []

        invoice_ids = [str(row.invoice_id) for row in rows]
        line_rows = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.invoice_id.in_(invoice_ids))
            .order_by(InvoiceLine.invoice_id.asc(), InvoiceLine.invoice_line_id.asc())
            .all()
        )

        lines_by_invoice: dict[str, list[InvoiceLine]] = {}
        for line in line_rows:
            lines_by_invoice.setdefault(str(line.invoice_id), []).append(line)

        return [_serialize_invoice(row, lines_by_invoice.get(str(row.invoice_id), [])) for row in rows]
    finally:
        db.close()


@router.get("/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(
    invoice_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _permission=Depends(require_operations_permission(PrivilegedPermission.INVOICES_VIEW)),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(Invoice)
            .filter(Invoice.company_id == company_id)
            .filter(Invoice.invoice_id == str(invoice_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Invoice not found")

        lines = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.invoice_id == str(invoice_id))
            .order_by(InvoiceLine.invoice_line_id.asc())
            .all()
        )
        return _serialize_invoice(row, lines)
    finally:
        db.close()


@router.post("/{invoice_id}/issue", response_model=InvoiceResponse)
def issue_invoice(
    invoice_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _permission=Depends(require_operations_permission(PrivilegedPermission.INVOICES_MANAGE)),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(Invoice)
            .filter(Invoice.company_id == company_id)
            .filter(Invoice.invoice_id == str(invoice_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Invoice not found")

        status = str(row.status)
        if status != "DRAFT":
            raise HTTPException(status_code=409, detail="Invoice can only be issued from DRAFT")

        row.status = "ISSUED"
        db.commit()
        db.refresh(row)

        lines = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.invoice_id == str(invoice_id))
            .order_by(InvoiceLine.invoice_line_id.asc())
            .all()
        )
        return _serialize_invoice(row, lines)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/{invoice_id}/send", response_model=InvoiceResponse)
def send_invoice(
    invoice_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _permission=Depends(require_operations_permission(PrivilegedPermission.INVOICES_MANAGE)),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(Invoice)
            .filter(Invoice.company_id == company_id)
            .filter(Invoice.invoice_id == str(invoice_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Invoice not found")

        status = str(row.status)
        if status == "SENT":
            raise HTTPException(status_code=409, detail="Invoice already SENT")
        if status != "ISSUED":
            raise HTTPException(status_code=409, detail="Invoice can only be sent from ISSUED")

        event_type = "INVOICE_SEND_READY"
        idempotency_key = f"{event_type}:{company_id}:{row.invoice_id}"
        existing = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.idempotency_key == idempotency_key)
            .one_or_none()
        )
        if existing is None:
            db.add(
                EventOutbox(
                    company_id=company_id,
                    event_type=event_type,
                    idempotency_key=idempotency_key,
                    payload={
                        "invoice_id": str(row.invoice_id),
                        "company_id": company_id,
                        "customer_name": str(row.customer_name),
                        "po_number": row.po_number,
                        "total_cents": int(row.total_cents),
                        "service_ticket_id": row.service_ticket_id,
                    },
                )
            )

        row.status = "SENT"
        db.commit()
        db.refresh(row)

        lines = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.invoice_id == str(invoice_id))
            .order_by(InvoiceLine.invoice_line_id.asc())
            .all()
        )
        return _serialize_invoice(row, lines)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()

from datetime import date, datetime

from pydantic import BaseModel


class InvoiceLineResponse(BaseModel):
    invoice_line_id: str
    invoice_id: str
    line_type: str
    description: str
    quantity: float
    unit_price_cents: int
    line_total_cents: int


class InvoiceResponse(BaseModel):
    invoice_id: str
    company_id: int
    customer_name: str
    customer_site_id: str
    job_purchase_order_id: str | None
    service_ticket_id: str
    invoice_date: date
    service_date: date
    po_number: str | None
    billing_address: str
    status: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    created_at: datetime
    lines: list[InvoiceLineResponse]

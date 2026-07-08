import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class Invoice(Base):
    __tablename__ = "invoices"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "service_ticket_id",
            name="uq_invoices_company_service_ticket",
        ),
        CheckConstraint(
            "status IN ('DRAFT','ISSUED','SENT','PAID','VOID')",
            name="ck_invoices_status_valid",
        ),
    )

    invoice_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String, nullable=False)
    customer_site_id = Column(
        String,
        ForeignKey("customer_sites.customer_site_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    job_purchase_order_id = Column(
        String,
        ForeignKey("job_purchase_orders.job_purchase_order_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    service_ticket_id = Column(
        String,
        ForeignKey("bin_service_tickets.bin_service_ticket_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_date = Column(Date, nullable=False)
    service_date = Column(Date, nullable=False)
    po_number = Column(String, nullable=True)
    billing_address = Column(String, nullable=False)
    status = Column(String, nullable=False, default="DRAFT", server_default="DRAFT", index=True)
    subtotal_cents = Column(Integer, nullable=False)
    tax_cents = Column(Integer, nullable=False, default=0, server_default="0")
    total_cents = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

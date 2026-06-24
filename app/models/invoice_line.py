import uuid

from sqlalchemy import Column, ForeignKey, Integer, Numeric, String

from app.database import Base


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    invoice_line_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id = Column(
        String,
        ForeignKey("invoices.invoice_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    line_type = Column(String, nullable=False, index=True)
    description = Column(String, nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)
    unit_price_cents = Column(Integer, nullable=False)
    line_total_cents = Column(Integer, nullable=False)

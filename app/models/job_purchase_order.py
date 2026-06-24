import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class JobPurchaseOrder(Base):
    __tablename__ = "job_purchase_orders"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "po_number",
            name="uq_job_purchase_orders_company_po_number",
        ),
        UniqueConstraint(
            "company_id",
            "job_purchase_order_id",
            name="uq_job_purchase_orders_company_po_id",
        ),
        CheckConstraint(
            "status IN ('DRAFT','ISSUED','CLOSED','VOID')",
            name="ck_job_purchase_orders_status_valid",
        ),
        CheckConstraint(
            "queue_status IN ('RECEIVED','UNMATCHED','MATCHED','READY_FOR_OPS','CLOSED')",
            name="ck_job_purchase_orders_queue_status_valid",
        ),
    )

    job_purchase_order_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True, index=True)
    po_number = Column(String, nullable=False, index=True)
    vendor_name = Column(String, nullable=True)
    vendor_email = Column(String, nullable=True)
    source_email_ingestion_event_id = Column(
        String,
        ForeignKey("email_ingestion_events.email_ingestion_event_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    status = Column(String, nullable=False, default="DRAFT", server_default="DRAFT", index=True)
    issued_date = Column(Date, nullable=True)
    queue_status = Column(String, nullable=False, default="RECEIVED", server_default="RECEIVED", index=True)
    matched_job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=True, index=True)
    matched_scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True, index=True)
    matched_customer_site_id = Column(
        String,
        ForeignKey("customer_sites.customer_site_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    reviewed_by_user_id = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

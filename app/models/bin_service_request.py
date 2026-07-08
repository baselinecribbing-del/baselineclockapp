import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, func

from app.database import Base


class BinServiceRequest(Base):
    __tablename__ = "bin_service_requests"

    __table_args__ = (
        CheckConstraint(
            "request_type IN ('DROP','SWAP','PICKUP')",
            name="ck_bin_service_requests_request_type_valid",
        ),
        CheckConstraint(
            "request_source IN ('MANUAL','EMAIL_INGESTION','PO_READY_FOR_OPS')",
            name="ck_bin_service_requests_request_source_valid",
        ),
        CheckConstraint(
            "status IN ('OPEN','SCHEDULED','COMPLETED','CANCELLED')",
            name="ck_bin_service_requests_status_valid",
        ),
    )

    bin_service_request_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    customer_site_id = Column(
        String,
        ForeignKey("customer_sites.customer_site_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    job_purchase_order_id = Column(
        String,
        ForeignKey("job_purchase_orders.job_purchase_order_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_email_ingestion_event_id = Column(
        String,
        ForeignKey("email_ingestion_events.email_ingestion_event_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    request_source = Column(String, nullable=False, default="MANUAL", server_default="MANUAL", index=True)
    request_type = Column(String, nullable=False)
    requested_for = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default="OPEN", server_default="OPEN", index=True)
    request_notes = Column(String, nullable=True)
    parsed_confidence = Column(Numeric(5, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

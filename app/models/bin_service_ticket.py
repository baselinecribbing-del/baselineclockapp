import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class BinServiceTicket(Base):
    __tablename__ = "bin_service_tickets"

    __table_args__ = (
        CheckConstraint(
            "service_type IN ('DROP','SWAP','PICKUP','DROP_BIN','SWAP_BIN','PICKUP_BIN','LANDFILL_DUMP')",
            name="ck_bin_service_tickets_service_type_valid",
        ),
        CheckConstraint(
            "status IN ('OPEN','SCHEDULED','DISPATCHED','COMPLETED','CANCELLED')",
            name="ck_bin_service_tickets_status_valid",
        ),
        CheckConstraint(
            "priority IN ('LOW','NORMAL','HIGH','URGENT')",
            name="ck_bin_service_tickets_priority_valid",
        ),
    )

    bin_service_ticket_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    bin_service_request_id = Column(
        String,
        ForeignKey("bin_service_requests.bin_service_request_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
    assigned_bin_asset_id = Column(
        String,
        ForeignKey("bin_assets.bin_asset_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    assigned_employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    assigned_vehicle_label = Column(String, nullable=True)
    service_type = Column(String, nullable=False)
    priority = Column(String, nullable=False, default="NORMAL", server_default="NORMAL", index=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    scheduled_date = Column(Date, nullable=True, index=True)
    scheduled_time_window = Column(String, nullable=True)
    status = Column(String, nullable=False, default="OPEN", server_default="OPEN", index=True)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    completed_by_user_id = Column(String, nullable=True)
    completion_notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

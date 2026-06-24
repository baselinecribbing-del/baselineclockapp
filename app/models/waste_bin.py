import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class WasteBin(Base):
    __tablename__ = "waste_bins"

    __table_args__ = (
        UniqueConstraint("company_id", "bin_number", name="uq_waste_bins_company_bin_number"),
        CheckConstraint(
            "status IN ('AVAILABLE','ON_SITE','IN_TRANSIT','AT_LANDFILL','OUT_OF_SERVICE')",
            name="ck_waste_bins_status_valid",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    bin_number = Column(String, nullable=False)
    capacity_yards = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="AVAILABLE", server_default="AVAILABLE", index=True)
    current_site_id = Column(
        String,
        ForeignKey("customer_sites.customer_site_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    current_ticket_id = Column(
        String,
        ForeignKey("bin_service_tickets.bin_service_ticket_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    last_service_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

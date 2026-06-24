import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func

from app.database import Base


class LandfillTrip(Base):
    __tablename__ = "landfill_trips"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "bin_service_ticket_id",
            name="uq_landfill_trips_company_ticket",
        ),
    )

    landfill_trip_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    bin_service_ticket_id = Column(
        String,
        ForeignKey("bin_service_tickets.bin_service_ticket_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    bin_asset_id = Column(
        String,
        ForeignKey("bin_assets.bin_asset_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dump_site_name = Column(String, nullable=False)
    receipt_photo_id = Column(
        String,
        ForeignKey("bin_service_photos.bin_service_photo_id", ondelete="RESTRICT"),
        nullable=True,
    )
    dump_cost_cents = Column(Integer, nullable=False)
    km_driven = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=False)

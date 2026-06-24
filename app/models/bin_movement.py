import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class BinMovement(Base):
    __tablename__ = "bin_movements"

    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('DROP','SWAP_OUT','SWAP_IN','LANDFILL_DUMP','RETURN_TO_YARD')",
            name="ck_bin_movements_movement_type_valid",
        ),
        CheckConstraint(
            "from_location_type IN ('SITE','LANDFILL','YARD')",
            name="ck_bin_movements_from_location_type_valid",
        ),
        CheckConstraint(
            "to_location_type IN ('SITE','LANDFILL','YARD')",
            name="ck_bin_movements_to_location_type_valid",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    bin_id = Column(
        String,
        ForeignKey("bin_assets.bin_asset_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    movement_type = Column(String, nullable=False, index=True)
    from_location_type = Column(String, nullable=False)
    from_location_id = Column(String, nullable=True)
    to_location_type = Column(String, nullable=False)
    to_location_id = Column(String, nullable=True)
    related_ticket_id = Column(
        String,
        ForeignKey("bin_service_tickets.bin_service_ticket_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    related_landfill_trip_id = Column(
        String,
        ForeignKey("landfill_trips.landfill_trip_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

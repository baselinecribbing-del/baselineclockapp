import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, func

from app.database import Base


class BinServicePhoto(Base):
    __tablename__ = "bin_service_photos"

    __table_args__ = (
        CheckConstraint(
            "photo_type IN ('DROP_PROOF','SWAP_PROOF','PICKUP_PROOF','RECEIPT')",
            name="ck_bin_service_photos_photo_type_valid",
        ),
    )

    bin_service_photo_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    bin_service_ticket_id = Column(
        String,
        ForeignKey("bin_service_tickets.bin_service_ticket_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    photo_type = Column(String, nullable=False, index=True)
    storage_key = Column(String, nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    captured_lat = Column(Numeric(9, 6), nullable=True)
    captured_lng = Column(Numeric(9, 6), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

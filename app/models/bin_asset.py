import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class BinAsset(Base):
    __tablename__ = "bin_assets"

    __table_args__ = (
        UniqueConstraint("company_id", "bin_number", name="uq_bin_assets_company_bin_number"),
        CheckConstraint(
            "status IN ('AVAILABLE','ASSIGNED','OUT_OF_SERVICE')",
            name="ck_bin_assets_status_valid",
        ),
    )

    bin_asset_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    bin_number = Column(String, nullable=False, index=True)
    bin_type = Column(String, nullable=False)
    bin_size = Column(String, nullable=False)
    status = Column(String, nullable=False, default="AVAILABLE", server_default="AVAILABLE", index=True)
    current_customer_site_id = Column(
        String,
        ForeignKey("customer_sites.customer_site_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    current_job_purchase_order_id = Column(
        String,
        ForeignKey("job_purchase_orders.job_purchase_order_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

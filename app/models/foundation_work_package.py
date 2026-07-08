import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class FoundationWorkPackage(Base):
    __tablename__ = "foundation_work_packages"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "job_purchase_order_id",
            name="uq_foundation_work_packages_company_po_id",
        ),
        CheckConstraint(
            "status IN ('READY','IN_PROGRESS','COMPLETED','CANCELLED')",
            name="ck_foundation_work_packages_status_valid",
        ),
    )

    foundation_work_package_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=False, index=True)
    job_purchase_order_id = Column(
        String,
        ForeignKey("job_purchase_orders.job_purchase_order_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status = Column(String, nullable=False, default="READY", server_default="READY", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

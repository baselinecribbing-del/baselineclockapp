import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class FiscalPeriod(Base):
    __tablename__ = "fiscal_periods"

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_fiscal_periods_company_name"),
        UniqueConstraint("company_id", "period_start", "period_end", name="uq_fiscal_periods_company_date_span"),
        CheckConstraint("period_start <= period_end", name="ck_fiscal_periods_date_order_valid"),
        CheckConstraint("status IN ('OPEN','CLOSED','LOCKED')", name="ck_fiscal_periods_status_valid"),
    )

    fiscal_period_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    name = Column(String(64), nullable=False, index=True)
    period_start = Column(Date, nullable=False, index=True)
    period_end = Column(Date, nullable=False, index=True)
    status = Column(String(16), nullable=False, default="OPEN", server_default="OPEN", index=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by_user_account_id = Column(
        String,
        ForeignKey("user_accounts.user_account_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

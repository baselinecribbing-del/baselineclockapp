import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.database import Base


class PayrollRun(Base):
    __tablename__ = "payroll_run"

    payroll_run_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False)
    pay_period_id = Column(String, ForeignKey("pay_period.pay_period_id"), nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    posted_at = Column(DateTime, nullable=True)

    # --- Columns added by later migrations; previously unmapped (drift → 500s). ---
    # finalize lifecycle (migration b1c2d3e4f5a7)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    finalized_by_user_id = Column(String, nullable=True)
    finalize_consistency_snapshot = Column(JSONB, nullable=True)
    # correction / supersession lifecycle (migration 0f1e2d3c4b5a)
    superseded_at = Column(DateTime(timezone=True), nullable=True)
    superseded_by_user_id = Column(String, nullable=True)
    superseded_by_payroll_run_id = Column(String, nullable=True)
    correction_reason = Column(String, nullable=True)

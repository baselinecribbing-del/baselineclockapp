import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.database import Base


class PayrollRun(Base):
    __tablename__ = "payroll_run"

    payroll_run_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False)
    pay_period_id = Column(String, ForeignKey("pay_period.pay_period_id"), nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    posted_at = Column(DateTime, nullable=True)

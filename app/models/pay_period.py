import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Integer, String

from app.database import Base


class PayPeriod(Base):
    __tablename__ = "pay_period"

    pay_period_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, index=True, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("start_date < end_date", name="ck_pay_period_start_before_end"),
    )

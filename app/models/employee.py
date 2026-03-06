from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String

from app.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    hourly_rate_cents = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("hourly_rate_cents >= 0", name="ck_employees_hourly_rate_cents_nonnegative"),
    )

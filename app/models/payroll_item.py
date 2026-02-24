from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class PayrollItem(Base):
    __tablename__ = "payroll_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, nullable=False, index=True)
    payroll_run_id = Column(
        String,
        ForeignKey("payroll_run.payroll_run_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    hours = Column(Numeric(10, 2), nullable=True)
    rate_cents = Column(Integer, nullable=True)
    gross_pay_cents = Column(Integer, nullable=False)
    meta = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    payroll_run = relationship("PayrollRun", backref="payroll_items")
    employee = relationship("Employee", backref="payroll_items")

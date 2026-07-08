import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class Paystub(Base):
    __tablename__ = "paystubs"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "payroll_run_id",
            "employee_id",
            name="uq_paystubs_company_run_employee",
        ),
        CheckConstraint(
            "delivery_status in ('PENDING','SENT')",
            name="ck_paystubs_delivery_status_valid",
        ),
        CheckConstraint(
            "total_deductions_cents >= 0",
            name="ck_paystubs_total_deductions_nonnegative",
        ),
        CheckConstraint(
            "net_pay_cents >= 0",
            name="ck_paystubs_net_pay_nonnegative",
        ),
    )

    paystub_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
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
    gross_pay_cents = Column(Integer, nullable=False)
    total_deductions_cents = Column(Integer, nullable=False, default=0, server_default="0")
    net_pay_cents = Column(Integer, nullable=False, default=0, server_default="0")
    delivery_status = Column(String, nullable=False, default="PENDING", server_default="PENDING", index=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    sent_by_user_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

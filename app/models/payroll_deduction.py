import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class PayrollDeduction(Base):
    __tablename__ = "payroll_deductions"

    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_payroll_deductions_amount_cents_nonnegative"),
        CheckConstraint(
            "calculation_source IN ('CONFIG', 'STATUTORY')",
            name="ck_payroll_deductions_calculation_source_known",
        ),
        UniqueConstraint(
            "company_id",
            "payroll_run_id",
            "employee_id",
            "deduction_type",
            name="uq_payroll_deductions_company_run_employee_type",
        ),
    )

    deduction_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
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
    paystub_id = Column(
        String,
        ForeignKey("paystubs.paystub_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    deduction_type = Column(String, nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)
    calculation_source = Column(String, nullable=False, server_default="CONFIG")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

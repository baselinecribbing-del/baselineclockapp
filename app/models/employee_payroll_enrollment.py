import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class EmployeePayrollEnrollment(Base):
    __tablename__ = "employee_payroll_enrollments"

    __table_args__ = (
        CheckConstraint(
            "category IN ('benefit','deduction')",
            name="ck_employee_payroll_enrollments_category_valid",
        ),
        CheckConstraint(
            "employee_amount_cents >= 0",
            name="ck_employee_payroll_enrollments_employee_amount_nonnegative",
        ),
        CheckConstraint(
            "employer_amount_cents >= 0",
            name="ck_employee_payroll_enrollments_employer_amount_nonnegative",
        ),
        CheckConstraint(
            "effective_end_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_employee_payroll_enrollments_effective_dates_valid",
        ),
    )

    enrollment_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(64), nullable=False, index=True)
    name = Column(String, nullable=False)
    category = Column(String(32), nullable=False, index=True)
    employee_amount_cents = Column(Integer, nullable=False, default=0, server_default="0")
    employer_amount_cents = Column(Integer, nullable=False, default=0, server_default="0")
    frequency = Column(String(64), nullable=False)
    effective_start_date = Column(Date, nullable=False, index=True)
    effective_end_date = Column(Date, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, func

from app.database import Base


class EmployeeVacationAssignment(Base):
    __tablename__ = "employee_vacation_assignments"

    __table_args__ = (
        CheckConstraint(
            "effective_end_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_employee_vacation_assignments_effective_dates_valid",
        ),
        CheckConstraint(
            "override_rate_percent IS NULL OR override_rate_percent >= 0",
            name="ck_employee_vacation_assignments_override_rate_nonnegative",
        ),
    )

    assignment_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    vacation_policy_id = Column(
        String,
        ForeignKey("vacation_policies.vacation_policy_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    effective_start_date = Column(Date, nullable=False, index=True)
    effective_end_date = Column(Date, nullable=True, index=True)
    override_rate_percent = Column(Numeric(7, 4), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

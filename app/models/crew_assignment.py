import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class CrewAssignment(Base):
    __tablename__ = "crew_assignments"

    __table_args__ = (
        CheckConstraint(
            "status IN ('ASSIGNED','ACKNOWLEDGED','COMPLETED','CANCELLED')",
            name="ck_crew_assignments_status_valid",
        ),
    )

    crew_assignment_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True, index=True)
    assigned_date = Column(Date, nullable=False, index=True)
    assigned_by_user_id = Column(String, nullable=False)
    assignment_notes = Column(String, nullable=True)
    status = Column(String, nullable=False, default="ASSIGNED", server_default="ASSIGNED", index=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by_employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

import uuid

from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class HazardAssessment(Base):
    __tablename__ = "hazard_assessments"

    hazard_assessment_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True, index=True)
    crew_assignment_id = Column(
        String,
        ForeignKey("crew_assignments.crew_assignment_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    completed_by_employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assessment_date = Column(Date, nullable=False, index=True)
    form_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

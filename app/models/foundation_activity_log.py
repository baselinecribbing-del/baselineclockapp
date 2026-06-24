import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class FoundationActivityLog(Base):
    __tablename__ = "foundation_activity_log"

    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('CLOCK_IN','CLOCK_OUT','JOB_PROGRESS_PHOTO','SITE_NOTE','ISSUE_REPORTED')",
            name="ck_foundation_activity_log_activity_type_valid",
        ),
    )

    foundation_activity_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    activity_type = Column(String, nullable=False, index=True)
    notes = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

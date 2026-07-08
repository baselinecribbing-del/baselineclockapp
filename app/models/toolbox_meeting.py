import uuid

from sqlalchemy import JSON, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class ToolboxMeeting(Base):
    __tablename__ = "toolbox_meetings"

    __table_args__ = (
        CheckConstraint(
            "attendee_count IS NULL OR attendee_count >= 0",
            name="ck_toolbox_meetings_attendee_count_nonnegative",
        ),
    )

    toolbox_meeting_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=True, index=True)
    scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True, index=True)
    meeting_date = Column(Date, nullable=False, index=True)
    completed_by_employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attendee_count = Column(Integer, nullable=True)
    form_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

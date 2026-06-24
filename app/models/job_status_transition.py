import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base


class JobStatusTransition(Base):
    __tablename__ = "job_status_transitions"

    job_status_transition_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=False, index=True)
    note = Column(Text, nullable=True)
    transitioned_by_user_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

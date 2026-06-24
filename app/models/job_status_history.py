from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class JobStatusHistory(Base):
    __tablename__ = "job_status_history"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=False, index=True)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

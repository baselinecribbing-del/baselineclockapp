from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base


class TimeEntry(Base):
    __tablename__ = "time_entries"

    time_entry_id = Column(String, primary_key=True, index=True)

    company_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, nullable=False, index=True)

    job_id = Column(Integer, nullable=False, index=True)
    scope_id = Column(Integer, nullable=False, index=True)

    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)

    status = Column(String, nullable=False, index=True)

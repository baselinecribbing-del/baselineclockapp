from sqlalchemy import Column, Date, DateTime, Integer, String

from app.database import Base


class Schedule(Base):
    __tablename__ = "schedules"

    schedule_id = Column(String, primary_key=True, index=True)

    company_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, nullable=False, index=True)

    scheduled_date = Column(Date, nullable=False, index=True)

    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=True)

    status = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)

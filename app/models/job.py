from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    site_lat = Column(Numeric(9, 6), nullable=True)
    site_lng = Column(Numeric(9, 6), nullable=True)
    site_radius_m = Column(Integer, nullable=True)

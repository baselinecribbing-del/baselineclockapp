import uuid

from sqlalchemy import Column, DateTime, Integer, String, func

from app.database import Base


class CrewGroup(Base):
    __tablename__ = "crew_groups"

    crew_group_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    created_by_user_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

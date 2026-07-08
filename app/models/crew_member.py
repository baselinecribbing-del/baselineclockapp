import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class CrewMember(Base):
    __tablename__ = "crew_members"

    crew_member_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    crew_id = Column(String, ForeignKey("crews.crew_id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    assigned_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    removed_at = Column(DateTime(timezone=True), nullable=True, index=True)

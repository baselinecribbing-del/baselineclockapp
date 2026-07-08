import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class CrewGroupMember(Base):
    __tablename__ = "crew_group_members"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "crew_group_id",
            "employee_id",
            name="uq_crew_group_members_company_group_employee",
        ),
    )

    crew_group_member_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    crew_group_id = Column(
        String,
        ForeignKey("crew_groups.crew_group_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

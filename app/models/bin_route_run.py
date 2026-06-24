import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base


class BinRouteRun(Base):
    __tablename__ = "bin_route_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('PLANNED','ACTIVE','COMPLETED','CANCELLED')",
            name="ck_bin_route_runs_status_valid",
        ),
    )

    route_run_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    route_label = Column(String, nullable=False, index=True)
    scheduled_date = Column(Date, nullable=False, index=True)
    status = Column(String, nullable=False, default="PLANNED", server_default="PLANNED", index=True)
    assigned_employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

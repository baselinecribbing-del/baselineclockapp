from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import Index

from app.database import Base


class PayrollRunAuditEvent(Base):
    __tablename__ = "payroll_run_audit_events"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    payroll_run_id = Column(
        String,
        ForeignKey("payroll_run.payroll_run_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    event_type = Column(String, nullable=False, index=True)
    actor_user_id = Column(String, nullable=True)
    event_timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    payload_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        Index("ix_payroll_run_audit_events_company_run_time", "company_id", "payroll_run_id", "event_timestamp"),
    )

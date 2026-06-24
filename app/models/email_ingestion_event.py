import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, JSON, String, func

from app.database import Base


class EmailIngestionEvent(Base):
    __tablename__ = "email_ingestion_events"

    __table_args__ = (
        CheckConstraint(
            "parse_status IN ('RECEIVED','PARSED','FAILED')",
            name="ck_email_ingestion_events_parse_status_valid",
        ),
    )

    email_ingestion_event_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    source_message_id = Column(String, nullable=False, index=True)
    sender_email = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    parse_status = Column(String, nullable=False, default="RECEIVED", server_default="RECEIVED", index=True)
    parsed_job_id = Column(Integer, nullable=True, index=True)
    parsed_scope_id = Column(Integer, nullable=True, index=True)
    parsed_po_number = Column(String, nullable=True, index=True)
    parse_notes = Column(String, nullable=True)
    raw_metadata = Column(JSON, nullable=True)

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, func

from app.database import Base


class JournalPostingAuditEvent(Base):
    __tablename__ = "journal_posting_audit_events"

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('POST_ATTEMPT')",
            name="ck_journal_posting_audit_events_event_type_valid",
        ),
        CheckConstraint(
            "result IN ('SUCCESS','FAILED')",
            name="ck_journal_posting_audit_events_result_valid",
        ),
    )

    journal_posting_audit_event_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    journal_entry_id = Column(String, nullable=False, index=True)
    event_type = Column(String(32), nullable=False, index=True)
    result = Column(String(16), nullable=False, index=True)
    actor_user_account_id = Column(String, nullable=True, index=True)
    source_type = Column(String(64), nullable=True, index=True)
    source_reference_id = Column(String(128), nullable=True, index=True)
    error_code = Column(String(64), nullable=True, index=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class FoundationsMessage(Base):
    __tablename__ = "foundations_messages"

    __table_args__ = (
        CheckConstraint(
            "message_type IN ('BROADCAST','JOB_INSTRUCTION','SAFETY_NOTICE')",
            name="ck_foundations_messages_message_type_valid",
        ),
    )

    foundations_message_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=True, index=True)
    scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True, index=True)
    message_type = Column(String, nullable=False, index=True)
    subject = Column(String, nullable=True)
    body = Column(String, nullable=False)
    created_by_user_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

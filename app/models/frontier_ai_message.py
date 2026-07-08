import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class FrontierAIMessage(Base):
    __tablename__ = "frontier_ai_messages"

    __table_args__ = (
        CheckConstraint("role IN ('USER','ASSISTANT')", name="ck_frontier_ai_messages_role_valid"),
    )

    frontier_ai_message_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        String,
        ForeignKey("frontier_ai_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = Column(Integer, nullable=False, index=True)
    user_id = Column(String, nullable=True, index=True)
    role = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    surface_context = Column(String, nullable=True)
    page_context = Column(JSONB, nullable=True)
    selected_record = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

import uuid

from sqlalchemy import Column, DateTime, Integer, String, func

from app.database import Base


class FrontierAIConversation(Base):
    __tablename__ = "frontier_ai_conversations"

    conversation_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

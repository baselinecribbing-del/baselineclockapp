import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class UserPasswordHistory(Base):
    __tablename__ = "user_password_history"

    user_password_history_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_account_id = Column(
        String,
        ForeignKey("user_accounts.user_account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = Column(Integer, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class UserRefreshToken(Base):
    __tablename__ = "user_refresh_tokens"

    user_refresh_token_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_account_id = Column(
        String,
        ForeignKey("user_accounts.user_account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    mfa_authenticated = Column(Boolean, nullable=False, default=False, server_default="false")
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

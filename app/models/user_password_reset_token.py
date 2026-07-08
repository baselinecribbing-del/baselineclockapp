import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class UserPasswordResetToken(Base):
    __tablename__ = "user_password_reset_tokens"

    __table_args__ = (
        CheckConstraint("purpose IN ('PASSWORD_RESET')", name="ck_user_password_reset_tokens_purpose_valid"),
    )

    user_password_reset_token_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_account_id = Column(
        String,
        ForeignKey("user_accounts.user_account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = Column(Integer, nullable=False, index=True)
    purpose = Column(String, nullable=False, default="PASSWORD_RESET", server_default="PASSWORD_RESET")
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

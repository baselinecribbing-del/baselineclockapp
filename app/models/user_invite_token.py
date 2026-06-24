import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class UserInviteToken(Base):
    __tablename__ = "user_invite_tokens"

    __table_args__ = (
        CheckConstraint("purpose IN ('ACCOUNT_INVITE')", name="ck_user_invite_tokens_purpose_valid"),
    )

    user_invite_token_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    email = Column(String(320), nullable=False, index=True)
    role = Column(String(32), nullable=False, default="MEMBER", server_default="MEMBER")
    invited_by_user_account_id = Column(
        String,
        ForeignKey("user_accounts.user_account_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    purpose = Column(String, nullable=False, default="ACCOUNT_INVITE", server_default="ACCOUNT_INVITE")
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

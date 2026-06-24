import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class UserMfaRecoveryCode(Base):
    __tablename__ = "user_mfa_recovery_codes"

    user_mfa_recovery_code_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_account_id = Column(
        String,
        ForeignKey("user_accounts.user_account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = Column(Integer, nullable=False, index=True)
    code_hash = Column(String, nullable=False, unique=True, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

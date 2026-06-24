import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class UserSmsCode(Base):
    __tablename__ = "user_sms_codes"

    user_sms_code_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_account_id = Column(
        String,
        ForeignKey("user_accounts.user_account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = Column(Integer, nullable=False, index=True)
    purpose = Column(String(32), nullable=False)
    phone_number = Column(String(32), nullable=False)
    code_hash = Column(String, nullable=False, unique=True, index=True)
    code_encrypted = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('PHONE_VERIFICATION', 'MFA_LOGIN')",
            name="ck_user_sms_codes_purpose_valid",
        ),
    )

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, func, text

from app.database import Base


class UserAccount(Base):
    __tablename__ = "user_accounts"

    user_account_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    role = Column(String(32), nullable=False, default="MEMBER", server_default="MEMBER")
    username = Column(String(128), nullable=False, unique=True, index=True)
    email = Column(String(320), nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    email_verified = Column(Boolean, nullable=False, default=False, server_default="false")
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    mfa_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    mfa_totp_secret_encrypted = Column(String, nullable=True)
    mfa_setup_started_at = Column(DateTime(timezone=True), nullable=True)
    mfa_enabled_at = Column(DateTime(timezone=True), nullable=True)
    phone_number = Column(String(32), nullable=True)
    phone_verified = Column(Boolean, nullable=False, default=False, server_default="false")
    phone_verified_at = Column(DateTime(timezone=True), nullable=True)
    preferred_mfa_method = Column(String(16), nullable=False, default="totp", server_default="totp")
    sms_mfa_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    can_access_operations = Column(Boolean, nullable=False, default=True, server_default="true")
    can_access_employee_self_service = Column(Boolean, nullable=False, default=False, server_default="false")
    linked_employee_id = Column(Integer, nullable=True, index=True)
    granted_permissions = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    employee_pin_hash = Column(String, nullable=True)
    employee_pin_failed_attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    employee_pin_lockout_until = Column(DateTime(timezone=True), nullable=True)
    employee_pin_changed_at = Column(DateTime(timezone=True), nullable=True)
    failed_login_attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    lockout_until = Column(DateTime(timezone=True), nullable=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

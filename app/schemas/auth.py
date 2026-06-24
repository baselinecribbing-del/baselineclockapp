from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)

    @field_validator("username", mode="before")
    @classmethod
    def _normalize_username(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        if not text:
            raise ValueError("username is required")
        return text


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthSessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_challenge_token: str | None = None
    available_mfa_methods: list[Literal["totp", "sms"]] = Field(default_factory=list)
    preferred_mfa_method: Literal["totp", "sms"] | None = None
    sms_phone_number_hint: str | None = None


class ForgotUsernameRequest(BaseModel):
    email: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        if "@" not in text:
            raise ValueError("email is required")
        return text


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        if "@" not in text:
            raise ValueError("email is required")
        return text


class UnlockAccountRequest(BaseModel):
    email: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        if "@" not in text:
            raise ValueError("email is required")
        return text


class RecoveryAcceptedResponse(BaseModel):
    status: str = "accepted"
    message: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=512)


class ResetPasswordResponse(BaseModel):
    status: str = "password_reset"
    password_changed_at: datetime


class ConfirmUnlockRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class ConfirmUnlockResponse(BaseModel):
    status: str = "account_unlocked"
    unlocked_at: datetime


class InviteUserRequest(BaseModel):
    email: str
    role: str = Field(default="MANAGER", min_length=1, max_length=32)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_invite_email(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        if "@" not in text:
            raise ValueError("email is required")
        return text

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: object) -> str:
        text = str(value or "").strip().upper()
        if not text:
            raise ValueError("role is required")
        return text


class CompleteInviteRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=512)

    @field_validator("username", mode="before")
    @classmethod
    def _normalize_complete_username(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        if not text:
            raise ValueError("username is required")
        return text


class CompleteInviteResponse(BaseModel):
    status: str = "invite_completed"
    user_account_id: str
    company_id: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=512)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1, max_length=512)


class LogoutResponse(BaseModel):
    status: str = "logged_out"


class MfaSetupResponse(BaseModel):
    status: str = "mfa_setup_started"
    secret: str
    provisioning_uri: str
    issuer: str
    account_name: str


class MfaVerifySetupRequest(BaseModel):
    code: str = Field(min_length=6, max_length=64)


class MfaVerifySetupResponse(BaseModel):
    status: str = "mfa_enabled"
    recovery_codes: list[str]


class MfaCompleteLoginRequest(BaseModel):
    challenge_token: str = Field(min_length=1, max_length=1024)
    code: str = Field(min_length=6, max_length=64)
    method: Literal["totp", "sms", "recovery_code"]


class MfaDisableRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    code: str = Field(min_length=6, max_length=64)


class MfaDisableResponse(BaseModel):
    status: str = "mfa_disabled"
    disabled_at: datetime


class PhoneVerificationStartRequest(BaseModel):
    phone_number: str = Field(min_length=7, max_length=32)


class PhoneVerificationStartResponse(BaseModel):
    status: str = "phone_verification_started"
    phone_number_hint: str
    expires_at: datetime


class PhoneVerificationConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class PhoneVerificationConfirmResponse(BaseModel):
    status: str = "phone_verified"
    phone_verified_at: datetime


class SendSmsMfaCodeRequest(BaseModel):
    challenge_token: str = Field(min_length=1, max_length=1024)


class SendSmsMfaCodeResponse(BaseModel):
    status: str = "sms_code_queued"
    phone_number_hint: str
    expires_at: datetime


class MfaPreferenceUpdateRequest(BaseModel):
    preferred_mfa_method: Literal["totp", "sms"]
    sms_mfa_enabled: bool | None = None


class MfaPreferenceUpdateResponse(BaseModel):
    status: str = "mfa_preference_updated"
    preferred_mfa_method: Literal["totp", "sms"]
    sms_mfa_enabled: bool

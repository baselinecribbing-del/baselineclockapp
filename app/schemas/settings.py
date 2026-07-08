from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SecurityProfileResponse(BaseModel):
    user_account_id: str
    company_id: int
    company_name: str
    selected_tier: str
    role: str
    username: str
    email: str
    email_verified: bool
    email_verified_at: datetime | None
    failed_login_attempt_count: int
    lockout_until: datetime | None
    password_changed_at: datetime
    phone_number_hint: str | None = None
    has_phone_number: bool
    phone_verified: bool
    phone_verified_at: datetime | None
    mfa_enabled: bool
    sms_mfa_enabled: bool
    available_mfa_methods: list[Literal["totp", "sms"]] = Field(default_factory=list)
    preferred_mfa_method: Literal["totp", "sms"] | None = None

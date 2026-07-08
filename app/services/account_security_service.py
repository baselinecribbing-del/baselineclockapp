from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import logging
import os
import secrets
import struct
import urllib.parse

from sqlalchemy.orm import Session

from app.models.company_profile import CompanyProfile
from app.models.event_outbox import EventOutbox
from app.models.user_account import UserAccount
from app.models.user_account_unlock_token import UserAccountUnlockToken
from app.models.user_invite_token import UserInviteToken
from app.models.user_mfa_recovery_code import UserMfaRecoveryCode
from app.models.user_password_history import UserPasswordHistory
from app.models.user_password_reset_token import UserPasswordResetToken
from app.models.user_refresh_token import UserRefreshToken
from app.models.user_sms_code import UserSmsCode
from app.services.access_control_service import VALID_ACCOUNT_ROLES, default_access_domains_for_role, normalize_account_role

logger = logging.getLogger(__name__)

PASSWORD_HASH_ITERATIONS = 120_000
LOCKOUT_FAILED_ATTEMPTS = 3
LOCKOUT_DURATION = timedelta(minutes=15)
PASSWORD_RESET_TTL = timedelta(hours=1)
ACCOUNT_UNLOCK_TTL = timedelta(hours=1)
INVITE_TOKEN_TTL = timedelta(days=7)
PASSWORD_HISTORY_LIMIT = 3
USERNAME_REMINDER_EVENT = "AUTH_USERNAME_REMINDER_EMAIL_READY"
PASSWORD_RESET_EVENT = "AUTH_PASSWORD_RESET_EMAIL_READY"
ACCOUNT_INVITE_EVENT = "AUTH_ACCOUNT_INVITE_EMAIL_READY"
ACCOUNT_UNLOCK_EVENT = "AUTH_ACCOUNT_UNLOCK_EMAIL_READY"
GENERIC_RECOVERY_MESSAGE = "If an eligible account exists, recovery instructions have been queued."
MFA_ISSUER = "Frontier"
MFA_RECOVERY_CODE_COUNT = 8
TOTP_TIME_STEP_SECONDS = 30
TOTP_DIGITS = 6
TOTP_WINDOW_STEPS = 1
SMS_CODE_DIGITS = 6
SMS_CODE_TTL = timedelta(minutes=10)
AUTH_SMS_CODE_EVENT = "AUTH_SMS_CODE_READY"
PHONE_VERIFICATION_PURPOSE = "PHONE_VERIFICATION"
MFA_LOGIN_SMS_PURPOSE = "MFA_LOGIN"
VALID_PREFERRED_MFA_METHODS = {"totp", "sms"}


class AuthenticationError(Exception):
    def __init__(self, code: str, message: str, *, lockout_until: datetime | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.lockout_until = lockout_until


class PasswordResetError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class InviteError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AccountUnlockError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MfaError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AuthenticatedAccount:
    account: UserAccount


@dataclass(frozen=True)
class PasswordResetResult:
    account: UserAccount


@dataclass(frozen=True)
class CompletedInviteResult:
    account: UserAccount


@dataclass(frozen=True)
class AccountUnlockResult:
    account: UserAccount


@dataclass(frozen=True)
class MfaSetupStartResult:
    account: UserAccount
    secret: str
    provisioning_uri: str


@dataclass(frozen=True)
class MfaSetupVerifyResult:
    account: UserAccount
    recovery_codes: list[str]


@dataclass(frozen=True)
class MfaDisableResult:
    account: UserAccount


@dataclass(frozen=True)
class MfaLoginVerificationResult:
    account: UserAccount


@dataclass(frozen=True)
class PhoneVerificationStartResult:
    account: UserAccount
    phone_number_hint: str
    expires_at: datetime


@dataclass(frozen=True)
class PhoneVerificationConfirmResult:
    account: UserAccount


@dataclass(frozen=True)
class SmsCodeDispatchResult:
    account: UserAccount
    phone_number_hint: str
    expires_at: datetime


@dataclass(frozen=True)
class MfaPreferenceUpdateResult:
    account: UserAccount


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_username(username: str) -> str:
    normalized = str(username or "").strip().lower()
    if not normalized:
        raise ValueError("username is required")
    return normalized


def _normalize_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized:
        raise ValueError("email is required")
    return normalized


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_sensitive_value_key() -> bytes:
    secret = os.getenv("MFA_SECRET_KEY") or os.getenv("JWT_SECRET") or ""
    if len(secret) < 32:
        raise ValueError("MFA_SECRET_KEY or JWT_SECRET must be at least 32 characters")
    return secret.encode("utf-8")


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _derive_stream_key(secret: bytes, nonce: bytes, length: int) -> bytes:
    blocks: list[bytes] = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        counter_bytes = counter.to_bytes(4, "big")
        blocks.append(hashlib.sha256(secret + nonce + counter_bytes).digest())
        counter += 1
    return b"".join(blocks)[:length]


def _encrypt_sensitive_value(value: str) -> str:
    plaintext = value.encode("utf-8")
    master_key = _get_sensitive_value_key()
    nonce = secrets.token_bytes(16)
    ciphertext = _xor_bytes(plaintext, _derive_stream_key(master_key, nonce, len(plaintext)))
    signature = hmac.new(master_key, nonce + ciphertext, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + ciphertext + signature).decode("ascii")


def _decrypt_sensitive_value(encrypted_value: str) -> str:
    raw = base64.urlsafe_b64decode(encrypted_value.encode("ascii"))
    if len(raw) < 16 + 32:
        raise ValueError("Encrypted value is invalid")
    nonce = raw[:16]
    signature = raw[-32:]
    ciphertext = raw[16:-32]
    master_key = _get_sensitive_value_key()
    expected = hmac.new(master_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Encrypted value is invalid")
    plaintext = _xor_bytes(ciphertext, _derive_stream_key(master_key, nonce, len(ciphertext)))
    return plaintext.decode("utf-8")


def _encrypt_mfa_secret(secret: str) -> str:
    return _encrypt_sensitive_value(secret)


def _decrypt_mfa_secret(encrypted_secret: str) -> str:
    return _decrypt_sensitive_value(encrypted_secret)


def _generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _normalize_totp_secret(secret: str) -> bytes:
    normalized = str(secret or "").strip().upper().replace(" ", "")
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def _totp_code_at(secret: str, for_time: datetime) -> str:
    secret_bytes = _normalize_totp_secret(secret)
    timestamp = int(for_time.timestamp())
    counter = timestamp // TOTP_TIME_STEP_SECONDS
    counter_bytes = struct.pack(">Q", counter)
    digest = hmac.new(secret_bytes, counter_bytes, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def _normalize_mfa_code(code: str) -> str:
    normalized = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(normalized) != TOTP_DIGITS:
        raise MfaError("invalid_mfa_code", "MFA code must be a 6-digit TOTP or a valid recovery code.")
    return normalized


def _normalize_recovery_code(code: str) -> str:
    normalized = str(code or "").strip().upper().replace(" ", "").replace("-", "")
    if len(normalized) < 8:
        raise MfaError("invalid_mfa_code", "MFA code must be a 6-digit TOTP or a valid recovery code.")
    return normalized


def _normalize_phone_number(phone_number: str) -> str:
    raw = str(phone_number or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise MfaError("invalid_phone_number", "Phone number is invalid.")
    if raw.startswith("+"):
        normalized_digits = digits
    elif len(digits) == 10:
        normalized_digits = f"1{digits}"
    else:
        normalized_digits = digits
    if len(normalized_digits) < 11 or len(normalized_digits) > 15:
        raise MfaError("invalid_phone_number", "Phone number is invalid.")
    return f"+{normalized_digits}"


def _mask_phone_number(phone_number: str) -> str:
    digits = "".join(ch for ch in str(phone_number or "") if ch.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"{'*' * max(0, len(digits) - 4)}{digits[-4:]}"


def _normalize_preferred_mfa_method(method: str | None) -> str:
    normalized = str(method or "totp").strip().lower()
    if normalized not in VALID_PREFERRED_MFA_METHODS:
        raise MfaError("invalid_preferred_mfa_method", "Preferred MFA method is not supported.")
    return normalized


def _normalize_sms_code(code: str) -> str:
    normalized = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(normalized) != SMS_CODE_DIGITS:
        raise MfaError("invalid_mfa_code", "MFA code is invalid.")
    return normalized


def _generate_sms_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(SMS_CODE_DIGITS))


def _build_provisioning_uri(*, secret: str, account: UserAccount) -> str:
    label = urllib.parse.quote(f"{MFA_ISSUER}:{account.email}")
    issuer = urllib.parse.quote(MFA_ISSUER)
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&digits={TOTP_DIGITS}&period={TOTP_TIME_STEP_SECONDS}"


def _generate_recovery_codes() -> list[str]:
    codes: list[str] = []
    for _ in range(MFA_RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(4).upper()
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def _replace_recovery_codes(*, db: Session, account: UserAccount, recovery_codes: list[str]) -> None:
    db.query(UserMfaRecoveryCode).filter(
        UserMfaRecoveryCode.user_account_id == account.user_account_id,
    ).delete(synchronize_session=False)
    for code in recovery_codes:
        db.add(
            UserMfaRecoveryCode(
                user_account_id=account.user_account_id,
                company_id=int(account.company_id),
                code_hash=_hash_token(_normalize_recovery_code(code)),
            )
        )


def _invalidate_recovery_codes(*, db: Session, account: UserAccount, used_at: datetime) -> None:
    db.query(UserMfaRecoveryCode).filter(
        UserMfaRecoveryCode.user_account_id == account.user_account_id,
        UserMfaRecoveryCode.used_at.is_(None),
    ).update({"used_at": used_at}, synchronize_session=False)


def _verify_totp(secret: str, code: str, *, now: datetime) -> bool:
    normalized = _normalize_mfa_code(code)
    for offset in range(-TOTP_WINDOW_STEPS, TOTP_WINDOW_STEPS + 1):
        candidate_time = now + timedelta(seconds=offset * TOTP_TIME_STEP_SECONDS)
        if hmac.compare_digest(_totp_code_at(secret, candidate_time), normalized):
            return True
    return False


def _verify_recovery_code(*, db: Session, account: UserAccount, code: str, now: datetime) -> bool:
    normalized = _normalize_recovery_code(code)
    row = (
        db.query(UserMfaRecoveryCode)
        .filter(
            UserMfaRecoveryCode.user_account_id == account.user_account_id,
            UserMfaRecoveryCode.code_hash == _hash_token(normalized),
            UserMfaRecoveryCode.used_at.is_(None),
        )
        .one_or_none()
    )
    if row is None:
        return False
    row.used_at = now
    db.add(row)
    return True


def _verify_totp_code_for_account(*, account: UserAccount, code: str, now: datetime) -> bool:
    if not account.mfa_totp_secret_encrypted:
        raise MfaError("mfa_not_configured", "MFA is not configured for this account.")
    secret = _decrypt_mfa_secret(str(account.mfa_totp_secret_encrypted))
    return _verify_totp(secret, code, now=now)


def _verify_mfa_code_for_account(*, db: Session, account: UserAccount, code: str) -> bool:
    now = _utcnow()
    try:
        if _verify_totp_code_for_account(account=account, code=code, now=now):
            return True
    except MfaError:
        pass
    return _verify_recovery_code(db=db, account=account, code=code, now=now)


def _invalidate_active_sms_codes(*, db: Session, account: UserAccount, purpose: str, used_at: datetime) -> None:
    db.query(UserSmsCode).filter(
        UserSmsCode.user_account_id == account.user_account_id,
        UserSmsCode.company_id == int(account.company_id),
        UserSmsCode.purpose == purpose,
        UserSmsCode.used_at.is_(None),
    ).update({"used_at": used_at}, synchronize_session=False)


def _issue_sms_code(*, db: Session, account: UserAccount, purpose: str, phone_number: str) -> UserSmsCode:
    now = _utcnow()
    normalized_phone_number = _normalize_phone_number(phone_number)
    _invalidate_active_sms_codes(db=db, account=account, purpose=purpose, used_at=now)
    raw_code = _generate_sms_code()
    row = UserSmsCode(
        user_account_id=account.user_account_id,
        company_id=int(account.company_id),
        purpose=purpose,
        phone_number=normalized_phone_number,
        code_hash=_hash_token(raw_code),
        code_encrypted=_encrypt_sensitive_value(raw_code),
        expires_at=now + SMS_CODE_TTL,
    )
    db.add(row)
    db.flush()
    _enqueue_outbox_sms(
        db=db,
        company_id=int(account.company_id),
        sms_code_id=row.user_sms_code_id,
        phone_number=normalized_phone_number,
        purpose=purpose,
        expires_at=row.expires_at,
    )
    return row


def _verify_sms_code(*, db: Session, account: UserAccount, purpose: str, code: str, now: datetime) -> bool:
    if not account.phone_number:
        return False
    normalized_code = _normalize_sms_code(code)
    normalized_phone_number = _normalize_phone_number(str(account.phone_number))
    row = (
        db.query(UserSmsCode)
        .filter(
            UserSmsCode.user_account_id == account.user_account_id,
            UserSmsCode.company_id == int(account.company_id),
            UserSmsCode.purpose == purpose,
            UserSmsCode.phone_number == normalized_phone_number,
            UserSmsCode.code_hash == _hash_token(normalized_code),
            UserSmsCode.used_at.is_(None),
        )
        .order_by(UserSmsCode.created_at.desc(), UserSmsCode.user_sms_code_id.desc())
        .one_or_none()
    )
    if row is None or row.expires_at <= now:
        return False
    row.used_at = now
    db.add(row)
    return True


def _sms_mfa_eligible(account: UserAccount) -> bool:
    return bool(account.phone_number) and bool(account.phone_verified)


def _sms_mfa_available(account: UserAccount) -> bool:
    return _sms_mfa_eligible(account) and bool(account.sms_mfa_enabled)


def get_available_mfa_methods_for_account(account: UserAccount) -> list[str]:
    methods = ["totp"]
    if _sms_mfa_available(account):
        methods.append("sms")
    return methods


def get_sms_phone_number_hint_for_account(account: UserAccount) -> str | None:
    if not _sms_mfa_available(account) or not account.phone_number:
        return None
    return _mask_phone_number(str(account.phone_number))


def get_phone_number_hint_for_account(account: UserAccount) -> str | None:
    if not account.phone_number:
        return None
    return _mask_phone_number(str(account.phone_number))


def _get_public_app_base_url() -> str:
    return os.getenv("PUBLIC_APP_BASE_URL", "https://app.frontier.local")


def _build_reset_link(token: str) -> str:
    base_url = os.getenv("PASSWORD_RESET_BASE_URL", f"{_get_public_app_base_url().rstrip('/')}/reset-password")
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}token={urllib.parse.quote(token)}"


def _build_invite_link(token: str) -> str:
    base_url = os.getenv("ACCOUNT_INVITE_BASE_URL", f"{_get_public_app_base_url().rstrip('/')}/complete-invite")
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}token={urllib.parse.quote(token)}"


def _build_unlock_link(token: str) -> str:
    base_url = os.getenv("ACCOUNT_UNLOCK_BASE_URL", f"{_get_public_app_base_url().rstrip('/')}/unlock-account")
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}token={urllib.parse.quote(token)}"


def _validate_role(role: str) -> str:
    normalized = str(role or "").strip().upper()
    if normalized not in VALID_ACCOUNT_ROLES:
        raise InviteError("invalid_role", "Role is not supported.")
    return normalize_account_role(normalized)


def _recent_password_history(*, db: Session, user_account_id: str) -> list[UserPasswordHistory]:
    return (
        db.query(UserPasswordHistory)
        .filter(UserPasswordHistory.user_account_id == user_account_id)
        .order_by(UserPasswordHistory.created_at.desc(), UserPasswordHistory.user_password_history_id.desc())
        .limit(PASSWORD_HISTORY_LIMIT)
        .all()
    )


def _enforce_password_history(*, db: Session, user_account_id: str, new_password: str) -> None:
    recent_history = _recent_password_history(db=db, user_account_id=user_account_id)
    if any(verify_password(new_password, row.password_hash) for row in recent_history):
        raise PasswordResetError(
            "password_reuse_not_allowed",
            "New password must not match any of the last 3 passwords.",
        )


def get_account_for_company(*, db: Session, user_account_id: str, company_id: int) -> UserAccount:
    account = (
        db.query(UserAccount)
        .filter(
            UserAccount.user_account_id == str(user_account_id),
            UserAccount.company_id == int(company_id),
        )
        .one_or_none()
    )
    if account is None:
        raise LookupError("user_account_not_found")
    return account


def hash_password(password: str) -> str:
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return "$".join(
        [
            "pbkdf2_sha256",
            str(PASSWORD_HASH_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_b64, digest_b64 = password_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    try:
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def create_user_account(
    *,
    db: Session,
    company_id: int,
    username: str,
    email: str,
    password: str,
    email_verified: bool = True,
    role: str = "MANAGER",
    user_account_id: str | None = None,
    can_access_operations: bool | None = None,
    can_access_employee_self_service: bool | None = None,
    linked_employee_id: int | None = None,
    granted_permissions: list[str] | None = None,
    commit: bool = True,
) -> UserAccount:
    now = _utcnow()
    normalized_username = _normalize_username(username)
    normalized_email = _normalize_email(email)
    normalized_role = _validate_role(role)
    default_operations_access, default_employee_self_service_access = default_access_domains_for_role(normalized_role)
    password_hash = hash_password(password)
    account = UserAccount(
        user_account_id=str(user_account_id) if user_account_id is not None else None,
        company_id=int(company_id),
        role=normalized_role,
        username=normalized_username,
        email=normalized_email,
        password_hash=password_hash,
        email_verified=bool(email_verified),
        email_verified_at=now if email_verified else None,
        can_access_operations=(
            default_operations_access if can_access_operations is None else bool(can_access_operations)
        ),
        can_access_employee_self_service=(
            default_employee_self_service_access
            if can_access_employee_self_service is None
            else bool(can_access_employee_self_service)
        ),
        linked_employee_id=None if linked_employee_id is None else int(linked_employee_id),
        granted_permissions=list(granted_permissions or []),
        password_changed_at=now,
    )
    db.add(account)
    db.flush()
    db.add(
        UserPasswordHistory(
            user_account_id=account.user_account_id,
            company_id=int(company_id),
            password_hash=password_hash,
            created_at=now,
        )
    )
    if commit:
        db.commit()
        reloaded = (
            db.query(UserAccount)
            .filter(UserAccount.user_account_id == str(account.user_account_id))
            .one_or_none()
        )
        if reloaded is not None:
            account = reloaded
    return account


def authenticate_user(*, db: Session, username: str, password: str) -> AuthenticatedAccount:
    now = _utcnow()
    account = (
        db.query(UserAccount)
        .filter(UserAccount.username == _normalize_username(username))
        .one_or_none()
    )
    if account is None:
        raise AuthenticationError("invalid_credentials", "Invalid username or password.")

    if account.lockout_until is not None and account.lockout_until <= now:
        _clear_lockout_state(account)
        db.add(account)
        db.commit()
        db.refresh(account)

    if account.lockout_until is not None and account.lockout_until > now:
        raise AuthenticationError(
            "account_locked",
            "Account is temporarily locked due to failed login attempts.",
            lockout_until=account.lockout_until,
        )

    if not verify_password(password, account.password_hash):
        account.failed_login_attempt_count = int(account.failed_login_attempt_count or 0) + 1
        if account.failed_login_attempt_count >= LOCKOUT_FAILED_ATTEMPTS:
            account.lockout_until = now + LOCKOUT_DURATION
            db.add(account)
            db.commit()
            db.refresh(account)
            raise AuthenticationError(
                "account_locked",
                "Account is temporarily locked due to failed login attempts.",
                lockout_until=account.lockout_until,
            )

        db.add(account)
        db.commit()
        raise AuthenticationError("invalid_credentials", "Invalid username or password.")

    _clear_lockout_state(account)
    db.add(account)
    db.commit()
    db.refresh(account)
    return AuthenticatedAccount(account=account)


def begin_mfa_setup(*, db: Session, user_account_id: str, company_id: int) -> MfaSetupStartResult:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    if bool(account.mfa_enabled):
        raise MfaError("mfa_already_enabled", "MFA is already enabled for this account.")

    now = _utcnow()
    secret = _generate_totp_secret()
    account.mfa_totp_secret_encrypted = _encrypt_mfa_secret(secret)
    account.mfa_setup_started_at = now
    account.mfa_enabled_at = None
    db.add(account)
    db.commit()
    db.refresh(account)
    return MfaSetupStartResult(
        account=account,
        secret=secret,
        provisioning_uri=_build_provisioning_uri(secret=secret, account=account),
    )


def verify_mfa_setup(*, db: Session, user_account_id: str, company_id: int, code: str) -> MfaSetupVerifyResult:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    if not account.mfa_totp_secret_encrypted or account.mfa_setup_started_at is None:
        raise MfaError("mfa_setup_not_started", "MFA setup has not been started for this account.")

    secret = _decrypt_mfa_secret(str(account.mfa_totp_secret_encrypted))
    now = _utcnow()
    if not _verify_totp(secret, code, now=now):
        raise MfaError("invalid_mfa_code", "MFA code is invalid.")

    account.mfa_enabled = True
    account.mfa_enabled_at = now
    account.preferred_mfa_method = _normalize_preferred_mfa_method(account.preferred_mfa_method)
    recovery_codes = _generate_recovery_codes()
    _replace_recovery_codes(db=db, account=account, recovery_codes=recovery_codes)
    _revoke_active_refresh_tokens(
        db=db,
        user_account_id=account.user_account_id,
        company_id=int(account.company_id),
        revoked_at=now,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return MfaSetupVerifyResult(account=account, recovery_codes=recovery_codes)


def disable_mfa(
    *,
    db: Session,
    user_account_id: str,
    company_id: int,
    current_password: str,
    code: str,
) -> MfaDisableResult:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    if not bool(account.mfa_enabled):
        raise MfaError("mfa_not_enabled", "MFA is not enabled for this account.")
    if not verify_password(current_password, account.password_hash):
        raise MfaError("current_password_incorrect", "Current password is incorrect.")
    if not _verify_mfa_code_for_account(db=db, account=account, code=code):
        raise MfaError("invalid_mfa_code", "MFA code is invalid.")

    now = _utcnow()
    account.mfa_enabled = False
    account.mfa_enabled_at = None
    account.mfa_setup_started_at = None
    account.mfa_totp_secret_encrypted = None
    _invalidate_recovery_codes(db=db, account=account, used_at=now)
    _revoke_active_refresh_tokens(
        db=db,
        user_account_id=account.user_account_id,
        company_id=int(account.company_id),
        revoked_at=now,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return MfaDisableResult(account=account)


def start_phone_verification(
    *,
    db: Session,
    user_account_id: str,
    company_id: int,
    phone_number: str,
) -> PhoneVerificationStartResult:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    normalized_phone_number = _normalize_phone_number(phone_number)
    account.phone_number = normalized_phone_number
    account.phone_verified = False
    account.phone_verified_at = None
    account.sms_mfa_enabled = False
    if account.preferred_mfa_method == "sms":
        account.preferred_mfa_method = "totp"
    row = _issue_sms_code(
        db=db,
        account=account,
        purpose=PHONE_VERIFICATION_PURPOSE,
        phone_number=normalized_phone_number,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return PhoneVerificationStartResult(
        account=account,
        phone_number_hint=_mask_phone_number(normalized_phone_number),
        expires_at=row.expires_at,
    )


def confirm_phone_verification(
    *,
    db: Session,
    user_account_id: str,
    company_id: int,
    code: str,
) -> PhoneVerificationConfirmResult:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    if not account.phone_number:
        raise MfaError("phone_number_not_configured", "Phone number is not configured for this account.")
    now = _utcnow()
    if not _verify_sms_code(db=db, account=account, purpose=PHONE_VERIFICATION_PURPOSE, code=code, now=now):
        raise MfaError("invalid_phone_verification_code", "Phone verification code is invalid or expired.")
    account.phone_verified = True
    account.phone_verified_at = now
    account.sms_mfa_enabled = True
    db.add(account)
    db.commit()
    db.refresh(account)
    return PhoneVerificationConfirmResult(account=account)


def send_mfa_sms_code(*, db: Session, user_account_id: str, company_id: int) -> SmsCodeDispatchResult:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    if not bool(account.mfa_enabled):
        raise MfaError("mfa_not_enabled", "MFA is not enabled for this account.")
    if not _sms_mfa_available(account):
        logger.warning(
            "sms_mfa_send_rejected",
            extra={"company_id": int(company_id), "user_account_id": str(user_account_id), "reason": "sms_mfa_unavailable"},
        )
        raise MfaError("sms_mfa_unavailable", "SMS MFA is not available for this account.")
    row = _issue_sms_code(
        db=db,
        account=account,
        purpose=MFA_LOGIN_SMS_PURPOSE,
        phone_number=str(account.phone_number),
    )
    logger.info(
        "sms_mfa_code_queued",
        extra={
            "company_id": int(company_id),
            "user_account_id": str(user_account_id),
            "sms_code_id": row.user_sms_code_id,
            "purpose": MFA_LOGIN_SMS_PURPOSE,
            "expires_at": row.expires_at.isoformat(),
        },
    )
    return SmsCodeDispatchResult(
        account=account,
        phone_number_hint=_mask_phone_number(str(account.phone_number)),
        expires_at=row.expires_at,
    )


def update_mfa_preference(
    *,
    db: Session,
    user_account_id: str,
    company_id: int,
    preferred_mfa_method: str,
    sms_mfa_enabled: bool | None = None,
) -> MfaPreferenceUpdateResult:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    normalized_preferred_method = _normalize_preferred_mfa_method(preferred_mfa_method)
    next_sms_mfa_enabled = bool(account.sms_mfa_enabled) if sms_mfa_enabled is None else bool(sms_mfa_enabled)

    if next_sms_mfa_enabled and (not bool(account.mfa_enabled) or not _sms_mfa_eligible(account)):
        raise MfaError("sms_mfa_unavailable", "SMS MFA is not available for this account.")
    if normalized_preferred_method == "sms" and not next_sms_mfa_enabled:
        raise MfaError("sms_mfa_unavailable", "SMS MFA is not available for this account.")

    if normalized_preferred_method == "sms" and (not bool(account.mfa_enabled) or not _sms_mfa_eligible(account)):
        raise MfaError("sms_mfa_unavailable", "SMS MFA is not available for this account.")

    account.sms_mfa_enabled = next_sms_mfa_enabled
    account.preferred_mfa_method = normalized_preferred_method
    db.add(account)
    db.commit()
    db.refresh(account)
    return MfaPreferenceUpdateResult(account=account)


def verify_mfa_login_code(
    *,
    db: Session,
    user_account_id: str,
    company_id: int,
    code: str,
    method: str,
) -> MfaLoginVerificationResult:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    if not bool(account.mfa_enabled):
        raise MfaError("mfa_not_enabled", "MFA is not enabled for this account.")
    normalized_method = str(method).strip().lower()
    now = _utcnow()
    if normalized_method == "sms":
        if not _sms_mfa_available(account):
            logger.warning(
                "sms_mfa_verify_rejected",
                extra={"company_id": int(company_id), "user_account_id": str(user_account_id), "reason": "sms_mfa_unavailable"},
            )
            raise MfaError("sms_mfa_unavailable", "SMS MFA is not available for this account.")
        if not _verify_sms_code(db=db, account=account, purpose=MFA_LOGIN_SMS_PURPOSE, code=code, now=now):
            logger.warning(
                "sms_mfa_verify_failed",
                extra={"company_id": int(company_id), "user_account_id": str(user_account_id), "reason": "invalid_or_expired_code"},
            )
            raise MfaError("invalid_mfa_code", "MFA code is invalid.")
        logger.info(
            "sms_mfa_verify_succeeded",
            extra={"company_id": int(company_id), "user_account_id": str(user_account_id), "method": "sms"},
        )
    elif normalized_method in {"totp", "recovery_code"}:
        if normalized_method == "totp":
            if not _verify_totp_code_for_account(account=account, code=code, now=now):
                raise MfaError("invalid_mfa_code", "MFA code is invalid.")
        else:
            if not _verify_recovery_code(db=db, account=account, code=code, now=now):
                raise MfaError("invalid_mfa_code", "MFA code is invalid.")
    else:
        raise MfaError("invalid_mfa_method", "MFA method is not supported.")
    return MfaLoginVerificationResult(account=account)


def _enqueue_outbox_email(
    *,
    db: Session,
    company_id: int,
    event_type: str,
    idempotency_key: str,
    payload: dict,
) -> None:
    existing = (
        db.query(EventOutbox)
        .filter(
            EventOutbox.company_id == int(company_id),
            EventOutbox.event_type == event_type,
            EventOutbox.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    if existing is not None:
        return

    db.add(
        EventOutbox(
            company_id=int(company_id),
            event_type=event_type,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    )


def _enqueue_outbox_sms(
    *,
    db: Session,
    company_id: int,
    sms_code_id: str,
    phone_number: str,
    purpose: str,
    expires_at: datetime,
) -> None:
    _enqueue_outbox_email(
        db=db,
        company_id=company_id,
        event_type=AUTH_SMS_CODE_EVENT,
        idempotency_key=str(sms_code_id),
        payload={
            "template": "auth_sms_code",
            "sms_code_id": str(sms_code_id),
            "purpose": purpose,
            "phone_number_hint": _mask_phone_number(phone_number),
            "expires_at": expires_at.isoformat(),
        },
    )


def _clear_lockout_state(account: UserAccount) -> None:
    account.failed_login_attempt_count = 0
    account.lockout_until = None


def _revoke_active_refresh_tokens(*, db: Session, user_account_id: str, company_id: int, revoked_at: datetime) -> None:
    db.query(UserRefreshToken).filter(
        UserRefreshToken.user_account_id == str(user_account_id),
        UserRefreshToken.company_id == int(company_id),
        UserRefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": revoked_at}, synchronize_session=False)


def request_username_reminder(*, db: Session, email: str) -> None:
    normalized_email = _normalize_email(email)
    account = (
        db.query(UserAccount)
        .filter(UserAccount.email == normalized_email)
        .one_or_none()
    )
    if account is None or not account.email_verified:
        db.commit()
        return

    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == int(account.company_id)).one_or_none()
    _enqueue_outbox_email(
        db=db,
        company_id=int(account.company_id),
        event_type=USERNAME_REMINDER_EVENT,
        idempotency_key=f"{account.user_account_id}:{secrets.token_hex(8)}",
        payload={
            "template": "username_reminder",
            "to_email": account.email,
            "username": account.username,
            "company_id": int(account.company_id),
            "company_name": None if profile is None else profile.company_name,
            "message": "Use this username to sign in to your Frontier account.",
        },
    )
    db.commit()


def request_password_reset(*, db: Session, email: str) -> None:
    normalized_email = _normalize_email(email)
    account = (
        db.query(UserAccount)
        .filter(UserAccount.email == normalized_email)
        .one_or_none()
    )
    if account is None or not account.email_verified:
        db.commit()
        return

    now = _utcnow()
    db.query(UserPasswordResetToken).filter(
        UserPasswordResetToken.user_account_id == account.user_account_id,
        UserPasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    reset_token = UserPasswordResetToken(
        user_account_id=account.user_account_id,
        company_id=int(account.company_id),
        token_hash=_hash_token(raw_token),
        expires_at=now + PASSWORD_RESET_TTL,
    )
    db.add(reset_token)
    db.flush()

    _enqueue_outbox_email(
        db=db,
        company_id=int(account.company_id),
        event_type=PASSWORD_RESET_EVENT,
        idempotency_key=reset_token.user_password_reset_token_id,
        payload={
            "template": "password_reset",
            "to_email": account.email,
            "username": account.username,
            "company_id": int(account.company_id),
            "reset_link": _build_reset_link(raw_token),
            "expires_at": reset_token.expires_at.isoformat(),
        },
    )
    db.commit()


def request_account_unlock(*, db: Session, email: str) -> None:
    normalized_email = _normalize_email(email)
    account = (
        db.query(UserAccount)
        .filter(UserAccount.email == normalized_email)
        .one_or_none()
    )
    if account is None or not account.email_verified:
        db.commit()
        return

    now = _utcnow()
    db.query(UserAccountUnlockToken).filter(
        UserAccountUnlockToken.user_account_id == account.user_account_id,
        UserAccountUnlockToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    unlock_token = UserAccountUnlockToken(
        user_account_id=account.user_account_id,
        company_id=int(account.company_id),
        token_hash=_hash_token(raw_token),
        expires_at=now + ACCOUNT_UNLOCK_TTL,
    )
    db.add(unlock_token)
    db.flush()

    _enqueue_outbox_email(
        db=db,
        company_id=int(account.company_id),
        event_type=ACCOUNT_UNLOCK_EVENT,
        idempotency_key=unlock_token.user_account_unlock_token_id,
        payload={
            "template": "account_unlock",
            "to_email": account.email,
            "username": account.username,
            "company_id": int(account.company_id),
            "unlock_link": _build_unlock_link(raw_token),
            "expires_at": unlock_token.expires_at.isoformat(),
        },
    )
    db.commit()


def reset_password(*, db: Session, token: str, new_password: str) -> PasswordResetResult:
    now = _utcnow()
    token_row = (
        db.query(UserPasswordResetToken)
        .filter(UserPasswordResetToken.token_hash == _hash_token(token))
        .one_or_none()
    )
    if token_row is None or token_row.used_at is not None:
        raise PasswordResetError("invalid_reset_token", "Reset token is invalid or has already been used.")
    if token_row.expires_at <= now:
        raise PasswordResetError("reset_token_expired", "Reset token has expired.")

    account = (
        db.query(UserAccount)
        .filter(UserAccount.user_account_id == token_row.user_account_id)
        .one_or_none()
    )
    if account is None:
        raise PasswordResetError("invalid_reset_token", "Reset token is invalid.")

    _enforce_password_history(db=db, user_account_id=account.user_account_id, new_password=new_password)
    new_password_hash = hash_password(new_password)
    account.password_hash = new_password_hash
    account.password_changed_at = now
    _clear_lockout_state(account)
    token_row.used_at = now
    db.query(UserPasswordResetToken).filter(
        UserPasswordResetToken.user_account_id == account.user_account_id,
        UserPasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    db.query(UserAccountUnlockToken).filter(
        UserAccountUnlockToken.user_account_id == account.user_account_id,
        UserAccountUnlockToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    _revoke_active_refresh_tokens(
        db=db,
        user_account_id=account.user_account_id,
        company_id=int(account.company_id),
        revoked_at=now,
    )
    db.add(account)
    db.add(token_row)
    db.add(
        UserPasswordHistory(
            user_account_id=account.user_account_id,
            company_id=int(account.company_id),
            password_hash=new_password_hash,
            created_at=now,
        )
    )
    db.commit()
    db.refresh(account)
    return PasswordResetResult(account=account)


def confirm_account_unlock(*, db: Session, token: str) -> AccountUnlockResult:
    now = _utcnow()
    token_row = (
        db.query(UserAccountUnlockToken)
        .filter(UserAccountUnlockToken.token_hash == _hash_token(token))
        .one_or_none()
    )
    if token_row is None or token_row.used_at is not None:
        raise AccountUnlockError("invalid_unlock_token", "Unlock token is invalid or has already been used.")
    if token_row.expires_at <= now:
        raise AccountUnlockError("unlock_token_expired", "Unlock token has expired.")

    account = (
        db.query(UserAccount)
        .filter(UserAccount.user_account_id == token_row.user_account_id)
        .one_or_none()
    )
    if account is None:
        raise AccountUnlockError("invalid_unlock_token", "Unlock token is invalid.")

    _clear_lockout_state(account)
    token_row.used_at = now
    db.query(UserAccountUnlockToken).filter(
        UserAccountUnlockToken.user_account_id == account.user_account_id,
        UserAccountUnlockToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    db.add(account)
    db.add(token_row)
    db.commit()
    db.refresh(account)
    return AccountUnlockResult(account=account)


def invite_user(
    *,
    db: Session,
    inviter_user_account_id: str,
    company_id: int,
    email: str,
    role: str,
) -> None:
    inviter = get_account_for_company(db=db, user_account_id=inviter_user_account_id, company_id=company_id)
    normalized_email = _normalize_email(email)
    normalized_role = _validate_role(role)

    existing_same_company = (
        db.query(UserAccount)
        .filter(UserAccount.company_id == int(company_id), UserAccount.email == normalized_email)
        .one_or_none()
    )
    if existing_same_company is not None:
        raise InviteError("user_account_exists", "An account already exists for this company and email.")

    existing_other_company = (
        db.query(UserAccount)
        .filter(UserAccount.email == normalized_email, UserAccount.company_id != int(company_id))
        .one_or_none()
    )
    if existing_other_company is not None:
        db.commit()
        return

    now = _utcnow()
    db.query(UserInviteToken).filter(
        UserInviteToken.company_id == int(company_id),
        UserInviteToken.email == normalized_email,
        UserInviteToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    invite = UserInviteToken(
        company_id=int(company_id),
        email=normalized_email,
        role=normalized_role,
        invited_by_user_account_id=inviter.user_account_id,
        token_hash=_hash_token(raw_token),
        expires_at=now + INVITE_TOKEN_TTL,
    )
    db.add(invite)
    db.flush()

    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == int(company_id)).one_or_none()
    _enqueue_outbox_email(
        db=db,
        company_id=int(company_id),
        event_type=ACCOUNT_INVITE_EVENT,
        idempotency_key=invite.user_invite_token_id,
        payload={
            "template": "account_invite",
            "to_email": normalized_email,
            "role": normalized_role,
            "company_id": int(company_id),
            "company_name": None if profile is None else profile.company_name,
            "invited_by_user_account_id": inviter.user_account_id,
            "invite_link": _build_invite_link(raw_token),
            "expires_at": invite.expires_at.isoformat(),
        },
    )
    db.commit()


def complete_invite(
    *,
    db: Session,
    token: str,
    username: str,
    password: str,
) -> CompletedInviteResult:
    now = _utcnow()
    invite = db.query(UserInviteToken).filter(UserInviteToken.token_hash == _hash_token(token)).one_or_none()
    if invite is None or invite.used_at is not None:
        raise InviteError("invalid_invite_token", "Invite token is invalid or has already been used.")
    if invite.expires_at <= now:
        raise InviteError("invite_token_expired", "Invite token has expired.")

    normalized_username = _normalize_username(username)
    existing_username = db.query(UserAccount).filter(UserAccount.username == normalized_username).one_or_none()
    if existing_username is not None:
        raise InviteError("username_unavailable", "Username is already in use.")

    existing_email = (
        db.query(UserAccount)
        .filter(UserAccount.email == invite.email, UserAccount.company_id == int(invite.company_id))
        .one_or_none()
    )
    if existing_email is not None:
        raise InviteError("user_account_exists", "An account already exists for this company and email.")

    account = create_user_account(
        db=db,
        company_id=int(invite.company_id),
        username=normalized_username,
        email=str(invite.email),
        password=password,
        email_verified=True,
        role=str(invite.role),
        commit=False,
    )
    invite.used_at = now
    db.add(account)
    db.add(invite)
    db.commit()
    db.refresh(account)
    return CompletedInviteResult(account=account)


def change_password(
    *,
    db: Session,
    user_account_id: str,
    company_id: int,
    current_password: str,
    new_password: str,
) -> PasswordResetResult:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    if not verify_password(current_password, account.password_hash):
        raise PasswordResetError("current_password_incorrect", "Current password is incorrect.")

    _enforce_password_history(db=db, user_account_id=account.user_account_id, new_password=new_password)
    now = _utcnow()
    new_password_hash = hash_password(new_password)
    account.password_hash = new_password_hash
    account.password_changed_at = now
    _clear_lockout_state(account)
    _revoke_active_refresh_tokens(
        db=db,
        user_account_id=account.user_account_id,
        company_id=int(account.company_id),
        revoked_at=now,
    )
    db.add(account)
    db.add(
        UserPasswordHistory(
            user_account_id=account.user_account_id,
            company_id=int(account.company_id),
            password_hash=new_password_hash,
            created_at=now,
        )
    )
    db.commit()
    db.refresh(account)
    return PasswordResetResult(account=account)


def get_security_profile(*, db: Session, user_account_id: str, company_id: int) -> tuple[UserAccount, CompanyProfile]:
    try:
        account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    except LookupError as exc:
        raise LookupError("security_profile_not_found") from exc

    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == int(company_id)).one_or_none()
    if profile is None:
        raise LookupError("company_profile_not_found")

    return account, profile

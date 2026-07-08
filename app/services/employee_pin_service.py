from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.user_account import UserAccount
from app.services.account_security_service import get_account_for_company, verify_password
from app.services.auth_service import revoke_refresh_tokens_for_user

EMPLOYEE_PIN_MIN_DIGITS = 4
EMPLOYEE_PIN_MAX_DIGITS = 6
EMPLOYEE_PIN_HASH_ITERATIONS = 120_000
EMPLOYEE_PIN_LOCKOUT_FAILED_ATTEMPTS = 5
EMPLOYEE_PIN_LOCKOUT_DURATION = timedelta(minutes=15)


class EmployeePinError(Exception):
    def __init__(self, code: str, message: str, *, lockout_until: datetime | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.lockout_until = lockout_until


@dataclass(frozen=True)
class EmployeePinResult:
    account: UserAccount
    verified_at: datetime | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_pin(pin: str) -> str:
    normalized = "".join(ch for ch in str(pin or "") if ch.isdigit())
    if len(normalized) < EMPLOYEE_PIN_MIN_DIGITS or len(normalized) > EMPLOYEE_PIN_MAX_DIGITS:
        raise EmployeePinError(
            "invalid_employee_pin",
            "Employee PIN must be 4 to 6 digits.",
        )
    if normalized != str(pin or "").strip():
        raise EmployeePinError(
            "invalid_employee_pin",
            "Employee PIN must be 4 to 6 digits.",
        )
    return normalized


def _hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        salt,
        EMPLOYEE_PIN_HASH_ITERATIONS,
    )
    return "$".join(
        [
            "pbkdf2_sha256_pin",
            str(EMPLOYEE_PIN_HASH_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        ]
    )


def _verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_b64, digest_b64 = pin_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256_pin":
        return False
    try:
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def _ensure_employee_self_service_account(account: UserAccount) -> None:
    if not bool(account.can_access_employee_self_service) or account.linked_employee_id is None:
        raise EmployeePinError(
            "employee_self_service_required",
            "Employee self-service access is required for employee PIN actions.",
        )


def _clear_pin_security_state(account: UserAccount) -> None:
    account.employee_pin_failed_attempt_count = 0
    account.employee_pin_lockout_until = None


def _maybe_clear_expired_lockout(account: UserAccount, *, now: datetime) -> None:
    if account.employee_pin_lockout_until is not None and account.employee_pin_lockout_until <= now:
        _clear_pin_security_state(account)


def _record_failed_attempt(account: UserAccount, *, now: datetime) -> None:
    failures = int(account.employee_pin_failed_attempt_count or 0) + 1
    account.employee_pin_failed_attempt_count = failures
    if failures >= EMPLOYEE_PIN_LOCKOUT_FAILED_ATTEMPTS:
        account.employee_pin_lockout_until = now + EMPLOYEE_PIN_LOCKOUT_DURATION


def _load_account(*, db: Session, user_account_id: str, company_id: int) -> UserAccount:
    account = get_account_for_company(db=db, user_account_id=user_account_id, company_id=company_id)
    _ensure_employee_self_service_account(account)
    return account


def set_employee_pin(*, db: Session, user_account_id: str, company_id: int, new_pin: str) -> EmployeePinResult:
    account = _load_account(db=db, user_account_id=user_account_id, company_id=company_id)
    if account.employee_pin_hash:
        raise EmployeePinError("employee_pin_already_set", "Employee PIN is already set.")
    normalized_pin = _normalize_pin(new_pin)
    now = _utcnow()
    account.employee_pin_hash = _hash_pin(normalized_pin)
    account.employee_pin_changed_at = now
    _clear_pin_security_state(account)
    db.add(account)
    db.commit()
    db.refresh(account)
    revoke_refresh_tokens_for_user(db=db, user_id=str(account.user_account_id), company_id=int(account.company_id))
    db.refresh(account)
    return EmployeePinResult(account=account)


def verify_employee_pin(*, db: Session, user_account_id: str, company_id: int, pin: str) -> EmployeePinResult:
    account = _load_account(db=db, user_account_id=user_account_id, company_id=company_id)
    if not account.employee_pin_hash:
        raise EmployeePinError("employee_pin_not_set", "Employee PIN has not been set.")
    normalized_pin = _normalize_pin(pin)
    now = _utcnow()
    _maybe_clear_expired_lockout(account, now=now)
    if account.employee_pin_lockout_until is not None and account.employee_pin_lockout_until > now:
        raise EmployeePinError(
            "employee_pin_locked",
            "Employee PIN is temporarily locked.",
            lockout_until=account.employee_pin_lockout_until,
        )
    if not _verify_pin(normalized_pin, str(account.employee_pin_hash)):
        _record_failed_attempt(account, now=now)
        db.add(account)
        db.commit()
        raise EmployeePinError(
            "invalid_employee_pin",
            "Employee PIN is invalid.",
            lockout_until=account.employee_pin_lockout_until,
        )
    _clear_pin_security_state(account)
    db.add(account)
    db.commit()
    db.refresh(account)
    return EmployeePinResult(account=account, verified_at=now)


def change_employee_pin(
    *,
    db: Session,
    user_account_id: str,
    company_id: int,
    current_pin: str,
    new_pin: str,
) -> EmployeePinResult:
    verified = verify_employee_pin(
        db=db,
        user_account_id=user_account_id,
        company_id=company_id,
        pin=current_pin,
    )
    normalized_pin = _normalize_pin(new_pin)
    account = verified.account
    account.employee_pin_hash = _hash_pin(normalized_pin)
    account.employee_pin_changed_at = _utcnow()
    _clear_pin_security_state(account)
    db.add(account)
    db.commit()
    db.refresh(account)
    revoke_refresh_tokens_for_user(db=db, user_id=str(account.user_account_id), company_id=int(account.company_id))
    db.refresh(account)
    return EmployeePinResult(account=account)


def reset_employee_pin(
    *,
    db: Session,
    user_account_id: str,
    company_id: int,
    current_password: str,
    new_pin: str,
) -> EmployeePinResult:
    account = _load_account(db=db, user_account_id=user_account_id, company_id=company_id)
    if not verify_password(current_password, str(account.password_hash)):
        raise EmployeePinError("invalid_password", "Current password is invalid.")
    normalized_pin = _normalize_pin(new_pin)
    account.employee_pin_hash = _hash_pin(normalized_pin)
    account.employee_pin_changed_at = _utcnow()
    _clear_pin_security_state(account)
    db.add(account)
    db.commit()
    db.refresh(account)
    revoke_refresh_tokens_for_user(db=db, user_id=str(account.user_account_id), company_id=int(account.company_id))
    db.refresh(account)
    return EmployeePinResult(account=account)

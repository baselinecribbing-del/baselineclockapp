import base64
from datetime import datetime, timezone
import hashlib
import hmac
import struct
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.event_outbox import EventOutbox
from app.models.user_account import UserAccount
from app.models.user_account_unlock_token import UserAccountUnlockToken
from app.models.user_invite_token import UserInviteToken
from app.models.user_mfa_recovery_code import UserMfaRecoveryCode
from app.models.user_password_reset_token import UserPasswordResetToken
from app.models.user_refresh_token import UserRefreshToken
from app.models.user_sms_code import UserSmsCode
from app.services.account_security_service import (
    ACCOUNT_INVITE_EVENT,
    ACCOUNT_UNLOCK_EVENT,
    AUTH_SMS_CODE_EVENT,
    MFA_LOGIN_SMS_PURPOSE,
    PASSWORD_RESET_EVENT,
    PHONE_VERIFICATION_PURPOSE,
    USERNAME_REMINDER_EVENT,
    _decrypt_sensitive_value,
    create_user_account,
)
from app.services.auth_service import verify_token

client = TestClient(app)


def _totp_code(secret: str, when: datetime | None = None) -> str:
    timestamp = int((when or datetime.now(timezone.utc)).timestamp())
    normalized = secret.strip().upper().replace(" ", "")
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    secret_bytes = base64.b32decode(normalized + padding, casefold=True)
    counter = timestamp // 30
    digest = hmac.new(secret_bytes, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % 1_000_000).zfill(6)


def _enable_mfa(username: str, password: str, company_id: int) -> dict:
    headers = _auth_headers_from_login(username, password, company_id)
    setup = client.post("/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    verify = client.post(
        "/auth/mfa/verify-setup",
        headers=headers,
        json={"code": _totp_code(setup.json()["secret"])},
    )
    assert verify.status_code == 200, verify.text
    return {
        "headers": headers,
        "setup": setup.json(),
        "verify": verify.json(),
    }


def _dev_auth_headers(company_id: int, user_id: str = "seed-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {token}"}


def _save_profile(company_id: int, selected_tier: str = "tier_3_full_system") -> None:
    resp = client.put(
        "/company/profile",
        headers=_dev_auth_headers(company_id),
        json={
            "company_name": f"Security Company {company_id}",
            "primary_trade": "Foundations",
            "country": "CA",
            "province_or_state": "AB",
            "selected_tier": selected_tier,
            "enabled_modules": ["jobs", "payroll", "field"],
            "onboarding_completed": True,
        },
    )
    assert resp.status_code == 200, resp.text


def _seed_account(
    *,
    company_id: int,
    username: str,
    email: str,
    password: str,
    email_verified: bool = True,
    role: str = "MANAGER",
) -> UserAccount:
    _save_profile(company_id)
    db = SessionLocal()
    try:
        account = create_user_account(
            db=db,
            company_id=company_id,
            username=username,
            email=email,
            password=password,
            email_verified=email_verified,
            role=role,
        )
        return account
    finally:
        db.close()


def _login(username: str, password: str) -> TestClient:
    return client.post("/auth/login", json={"username": username, "password": password})


def _auth_headers_from_login(username: str, password: str, company_id: int) -> dict[str, str]:
    response = _login(username, password)
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _extract_link_token(event_type: str, link_key: str) -> str:
    db = SessionLocal()
    try:
        row = (
            db.query(EventOutbox)
            .filter(EventOutbox.event_type == event_type)
            .order_by(EventOutbox.id.desc())
            .first()
        )
        assert row is not None
        parsed = urlparse(str(row.payload[link_key]))
        values = parse_qs(parsed.query).get("token") or []
        assert values
        return values[0]
    finally:
        db.close()


def _latest_sms_code(*, user_account_id: str, purpose: str) -> tuple[UserSmsCode, str]:
    db = SessionLocal()
    try:
        row = (
            db.query(UserSmsCode)
            .filter(
                UserSmsCode.user_account_id == user_account_id,
                UserSmsCode.purpose == purpose,
            )
            .order_by(UserSmsCode.created_at.desc(), UserSmsCode.user_sms_code_id.desc())
            .first()
        )
        assert row is not None
        return row, _decrypt_sensitive_value(row.code_encrypted)
    finally:
        db.close()


def _start_phone_verification(headers: dict[str, str], phone_number: str) -> dict:
    response = client.post(
        "/auth/phone/start-verification",
        headers=headers,
        json={"phone_number": phone_number},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_failed_login_attempts_increment_and_lockout_after_three_failures():
    account = _seed_account(
        company_id=66101,
        username="lockout-user",
        email="lockout@example.com",
        password="InitialPass#1",
    )

    first = _login("lockout-user", "wrong-pass")
    second = _login("lockout-user", "wrong-pass")
    third = _login("lockout-user", "wrong-pass")

    assert first.status_code == 401
    assert first.json()["detail"]["code"] == "invalid_credentials"
    assert second.status_code == 401
    assert second.json()["detail"]["code"] == "invalid_credentials"
    assert third.status_code == 423
    assert third.json()["detail"]["code"] == "account_locked"
    assert third.json()["detail"]["lockout_until"]

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        assert refreshed.failed_login_attempt_count == 3
        assert refreshed.lockout_until is not None
    finally:
        db.close()


def test_successful_login_resets_failed_attempt_state_and_returns_company_scoped_token():
    account = _seed_account(
        company_id=66102,
        username="reset-attempts-user",
        email="reset-attempts@example.com",
        password="ValidPass#1",
    )

    bad = _login("reset-attempts-user", "wrong-pass")
    assert bad.status_code == 401

    good = _login("reset-attempts-user", "ValidPass#1")
    assert good.status_code == 200, good.text
    token = good.json()["access_token"]
    claims = verify_token(token)
    assert claims["company_id"] == 66102
    assert claims["sub"] == account.user_account_id

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        assert refreshed.failed_login_attempt_count == 0
        assert refreshed.lockout_until is None
    finally:
        db.close()


def test_login_returns_refresh_token_and_expiry_metadata():
    _seed_account(
        company_id=66114,
        username="refresh-login-user",
        email="refresh-login@example.com",
        password="RefreshPass#1",
    )

    response = _login("refresh-login-user", "RefreshPass#1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 28800
    assert body["token_type"] == "bearer"

    access_claims = verify_token(body["access_token"])
    assert access_claims["company_id"] == 66114

    db = SessionLocal()
    try:
        rows = db.query(UserRefreshToken).filter(UserRefreshToken.company_id == 66114).all()
        assert len(rows) == 1
        assert rows[0].user_account_id == access_claims["sub"]
        assert rows[0].revoked_at is None
    finally:
        db.close()


def test_refresh_endpoint_issues_new_access_token_and_rotates_refresh_token():
    account = _seed_account(
        company_id=66115,
        username="refresh-rotate-user",
        email="refresh-rotate@example.com",
        password="RefreshPass#1",
    )

    login = _login("refresh-rotate-user", "RefreshPass#1")
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]

    refreshed = client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["refresh_token"] != refresh_token
    claims = verify_token(body["access_token"])
    assert claims["sub"] == account.user_account_id
    assert claims["company_id"] == 66115

    replay = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert replay.status_code == 401
    assert replay.json()["detail"]["code"] == "invalid_refresh_token"

    db = SessionLocal()
    try:
        rows = (
            db.query(UserRefreshToken)
            .filter(UserRefreshToken.user_account_id == account.user_account_id)
            .order_by(UserRefreshToken.created_at.asc())
            .all()
        )
        assert len(rows) == 2
        assert rows[0].revoked_at is not None
        assert rows[1].revoked_at is None
    finally:
        db.close()


def test_refresh_rejects_expired_refresh_token():
    account = _seed_account(
        company_id=66116,
        username="refresh-expired-user",
        email="refresh-expired@example.com",
        password="RefreshPass#1",
    )

    login = _login("refresh-expired-user", "RefreshPass#1")
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]

    db = SessionLocal()
    try:
        row = db.query(UserRefreshToken).filter(UserRefreshToken.user_account_id == account.user_account_id).one()
        row.expires_at = row.created_at
        db.add(row)
        db.commit()
    finally:
        db.close()

    expired = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert expired.status_code == 401
    assert expired.json()["detail"]["code"] == "refresh_token_expired"


def test_logout_invalidates_refresh_token():
    account = _seed_account(
        company_id=66117,
        username="refresh-logout-user",
        email="refresh-logout@example.com",
        password="RefreshPass#1",
    )

    login = _login("refresh-logout-user", "RefreshPass#1")
    assert login.status_code == 200, login.text
    body = login.json()

    logout = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {body['access_token']}", "X-Company-Id": "66117"},
        json={"refresh_token": body["refresh_token"]},
    )
    assert logout.status_code == 200, logout.text
    assert logout.json()["status"] == "logged_out"

    refresh = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert refresh.status_code == 401
    assert refresh.json()["detail"]["code"] == "invalid_refresh_token"

    db = SessionLocal()
    try:
        row = db.query(UserRefreshToken).filter(UserRefreshToken.user_account_id == account.user_account_id).one()
        assert row.revoked_at is not None
    finally:
        db.close()


def test_refresh_token_company_isolation_is_preserved():
    account_a = _seed_account(
        company_id=66118,
        username="refresh-company-a",
        email="refresh-company-a@example.com",
        password="RefreshPass#1",
    )
    account_b = _seed_account(
        company_id=66119,
        username="refresh-company-b",
        email="refresh-company-b@example.com",
        password="RefreshPass#1",
    )

    login_a = _login("refresh-company-a", "RefreshPass#1")
    login_b = _login("refresh-company-b", "RefreshPass#1")
    assert login_a.status_code == 200, login_a.text
    assert login_b.status_code == 200, login_b.text

    logout_a = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {login_a.json()['access_token']}", "X-Company-Id": "66118"},
    )
    assert logout_a.status_code == 200, logout_a.text

    refresh_a = client.post("/auth/refresh", json={"refresh_token": login_a.json()["refresh_token"]})
    refresh_b = client.post("/auth/refresh", json={"refresh_token": login_b.json()["refresh_token"]})

    assert refresh_a.status_code == 401
    assert refresh_a.json()["detail"]["code"] == "invalid_refresh_token"
    assert refresh_b.status_code == 200, refresh_b.text
    assert verify_token(refresh_b.json()["access_token"])["company_id"] == 66119

    db = SessionLocal()
    try:
        rows = db.query(UserRefreshToken).order_by(UserRefreshToken.company_id.asc()).all()
        assert len(rows) == 3
        company_ids = {(row.user_account_id, row.company_id, row.revoked_at is None) for row in rows}
        assert (account_a.user_account_id, 66118, False) in company_ids
        assert (account_b.user_account_id, 66119, False) in company_ids
        assert (account_b.user_account_id, 66119, True) in company_ids
    finally:
        db.close()


def test_mfa_setup_initiation_returns_provisioning_details():
    account = _seed_account(
        company_id=66124,
        username="mfa-setup-user",
        email="mfa-setup@example.com",
        password="MfaSetupPass#1",
    )
    headers = _auth_headers_from_login("mfa-setup-user", "MfaSetupPass#1", 66124)

    setup = client.post("/auth/mfa/setup", headers=headers)

    assert setup.status_code == 200, setup.text
    body = setup.json()
    assert body["status"] == "mfa_setup_started"
    assert body["secret"]
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert body["account_name"] == "mfa-setup@example.com"

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        assert refreshed.mfa_enabled is False
        assert refreshed.mfa_totp_secret_encrypted
        assert refreshed.mfa_totp_secret_encrypted != body["secret"]
        assert refreshed.mfa_setup_started_at is not None
    finally:
        db.close()


def test_mfa_setup_verification_enables_mfa_and_returns_recovery_codes():
    account = _seed_account(
        company_id=66125,
        username="mfa-verify-user",
        email="mfa-verify@example.com",
        password="MfaVerifyPass#1",
    )
    headers = _auth_headers_from_login("mfa-verify-user", "MfaVerifyPass#1", 66125)
    setup = client.post("/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200, setup.text

    verify = client.post(
        "/auth/mfa/verify-setup",
        headers=headers,
        json={"code": _totp_code(setup.json()["secret"])},
    )

    assert verify.status_code == 200, verify.text
    body = verify.json()
    assert body["status"] == "mfa_enabled"
    assert len(body["recovery_codes"]) == 8

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        recovery_rows = db.query(UserMfaRecoveryCode).filter(UserMfaRecoveryCode.user_account_id == account.user_account_id).all()
        assert refreshed.mfa_enabled is True
        assert refreshed.mfa_enabled_at is not None
        assert len(recovery_rows) == 8
    finally:
        db.close()


def test_mfa_enabled_login_requires_second_factor():
    _seed_account(
        company_id=66126,
        username="mfa-login-user",
        email="mfa-login@example.com",
        password="MfaLoginPass#1",
    )
    _enable_mfa("mfa-login-user", "MfaLoginPass#1", 66126)

    login = _login("mfa-login-user", "MfaLoginPass#1")

    assert login.status_code == 200, login.text
    body = login.json()
    assert body["mfa_required"] is True
    assert body["mfa_challenge_token"]
    assert body["access_token"] is None
    assert body["refresh_token"] is None


def test_valid_totp_completes_mfa_login_and_issues_session():
    _seed_account(
        company_id=66127,
        username="mfa-complete-user",
        email="mfa-complete@example.com",
        password="MfaCompletePass#1",
    )
    enabled = _enable_mfa("mfa-complete-user", "MfaCompletePass#1", 66127)

    login = _login("mfa-complete-user", "MfaCompletePass#1")
    complete = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login.json()["mfa_challenge_token"],
            "code": _totp_code(enabled["setup"]["secret"]),
            "method": "totp",
        },
    )

    assert complete.status_code == 200, complete.text
    body = complete.json()
    assert body["access_token"]
    assert body["refresh_token"]
    refresh = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert refresh.status_code == 200, refresh.text


def test_invalid_totp_is_rejected_for_mfa_login():
    _seed_account(
        company_id=66128,
        username="mfa-invalid-user",
        email="mfa-invalid@example.com",
        password="MfaInvalidPass#1",
    )
    _enable_mfa("mfa-invalid-user", "MfaInvalidPass#1", 66128)

    login = _login("mfa-invalid-user", "MfaInvalidPass#1")
    complete = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login.json()["mfa_challenge_token"],
            "code": "000000",
            "method": "totp",
        },
    )

    assert complete.status_code == 401
    assert complete.json()["detail"]["code"] == "invalid_mfa_code"


def test_valid_recovery_code_completes_login_once_and_reuse_fails():
    _seed_account(
        company_id=66129,
        username="mfa-recovery-user",
        email="mfa-recovery@example.com",
        password="MfaRecoveryPass#1",
    )
    enabled = _enable_mfa("mfa-recovery-user", "MfaRecoveryPass#1", 66129)
    recovery_code = enabled["verify"]["recovery_codes"][0]

    login = _login("mfa-recovery-user", "MfaRecoveryPass#1")
    complete = client.post(
        "/auth/mfa/complete-login",
        json={"challenge_token": login.json()["mfa_challenge_token"], "code": recovery_code, "method": "recovery_code"},
    )
    assert complete.status_code == 200, complete.text

    second_login = _login("mfa-recovery-user", "MfaRecoveryPass#1")
    reused = client.post(
        "/auth/mfa/complete-login",
        json={"challenge_token": second_login.json()["mfa_challenge_token"], "code": recovery_code, "method": "recovery_code"},
    )
    assert reused.status_code == 401
    assert reused.json()["detail"]["code"] == "invalid_mfa_code"


def test_disabling_mfa_requires_valid_confirmation_and_restores_password_only_login():
    _seed_account(
        company_id=66130,
        username="mfa-disable-user",
        email="mfa-disable@example.com",
        password="MfaDisablePass#1",
    )
    enabled = _enable_mfa("mfa-disable-user", "MfaDisablePass#1", 66130)

    login = _login("mfa-disable-user", "MfaDisablePass#1")
    complete = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login.json()["mfa_challenge_token"],
            "code": _totp_code(enabled["setup"]["secret"]),
            "method": "totp",
        },
    )
    assert complete.status_code == 200, complete.text

    disable = client.post(
        "/auth/mfa/disable",
        headers={"Authorization": f"Bearer {complete.json()['access_token']}", "X-Company-Id": "66130"},
        json={"current_password": "MfaDisablePass#1", "code": _totp_code(enabled["setup"]["secret"])},
    )
    assert disable.status_code == 200, disable.text
    assert disable.json()["status"] == "mfa_disabled"

    login_after_disable = _login("mfa-disable-user", "MfaDisablePass#1")
    assert login_after_disable.status_code == 200, login_after_disable.text
    assert login_after_disable.json()["mfa_required"] is False
    assert login_after_disable.json()["access_token"]


def test_mfa_login_company_and_user_isolation_is_preserved():
    _seed_account(
        company_id=66131,
        username="mfa-isolation-a",
        email="mfa-isolation-a@example.com",
        password="MfaIsolationPass#1",
    )
    _seed_account(
        company_id=66132,
        username="mfa-isolation-b",
        email="mfa-isolation-b@example.com",
        password="MfaIsolationPass#1",
    )
    enabled_a = _enable_mfa("mfa-isolation-a", "MfaIsolationPass#1", 66131)
    enabled_b = _enable_mfa("mfa-isolation-b", "MfaIsolationPass#1", 66132)

    login_a = _login("mfa-isolation-a", "MfaIsolationPass#1")
    invalid_cross = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login_a.json()["mfa_challenge_token"],
            "code": enabled_b["verify"]["recovery_codes"][0],
            "method": "recovery_code",
        },
    )
    assert invalid_cross.status_code == 401
    assert invalid_cross.json()["detail"]["code"] == "invalid_mfa_code"

    login_b = _login("mfa-isolation-b", "MfaIsolationPass#1")
    valid_b = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login_b.json()["mfa_challenge_token"],
            "code": _totp_code(enabled_b["setup"]["secret"]),
            "method": "totp",
        },
    )
    assert valid_b.status_code == 200, valid_b.text
    assert verify_token(valid_b.json()["access_token"])["company_id"] == 66132


def test_mfa_complete_login_requires_explicit_method():
    _seed_account(
        company_id=66141,
        username="mfa-method-required-user",
        email="mfa-method-required@example.com",
        password="MfaMethodPass#1",
    )
    enabled = _enable_mfa("mfa-method-required-user", "MfaMethodPass#1", 66141)

    login = _login("mfa-method-required-user", "MfaMethodPass#1")
    complete = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login.json()["mfa_challenge_token"],
            "code": _totp_code(enabled["setup"]["secret"]),
        },
    )

    assert complete.status_code == 422


def test_totp_method_does_not_fallback_to_recovery_code():
    _seed_account(
        company_id=66142,
        username="mfa-no-fallback-totp",
        email="mfa-no-fallback-totp@example.com",
        password="MfaNoFallbackPass#1",
    )
    enabled = _enable_mfa("mfa-no-fallback-totp", "MfaNoFallbackPass#1", 66142)
    recovery_code = enabled["verify"]["recovery_codes"][0]

    login = _login("mfa-no-fallback-totp", "MfaNoFallbackPass#1")
    complete = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login.json()["mfa_challenge_token"],
            "code": recovery_code,
            "method": "totp",
        },
    )

    assert complete.status_code == 401
    assert complete.json()["detail"]["code"] == "invalid_mfa_code"


def test_recovery_code_method_does_not_fallback_to_totp():
    _seed_account(
        company_id=66143,
        username="mfa-no-fallback-recovery",
        email="mfa-no-fallback-recovery@example.com",
        password="MfaNoFallbackPass#1",
    )
    enabled = _enable_mfa("mfa-no-fallback-recovery", "MfaNoFallbackPass#1", 66143)

    login = _login("mfa-no-fallback-recovery", "MfaNoFallbackPass#1")
    complete = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login.json()["mfa_challenge_token"],
            "code": _totp_code(enabled["setup"]["secret"]),
            "method": "recovery_code",
        },
    )

    assert complete.status_code == 401
    assert complete.json()["detail"]["code"] == "invalid_mfa_code"


def test_phone_verification_start_stores_phone_and_queues_sms_code():
    account = _seed_account(
        company_id=66133,
        username="phone-start-user",
        email="phone-start@example.com",
        password="PhoneStartPass#1",
    )
    headers = _auth_headers_from_login("phone-start-user", "PhoneStartPass#1", 66133)

    response = client.post(
        "/auth/phone/start-verification",
        headers=headers,
        json={"phone_number": "(780) 555-0101"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "phone_verification_started"
    assert body["phone_number_hint"].endswith("0101")

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        sms_row = db.query(UserSmsCode).filter(UserSmsCode.user_account_id == account.user_account_id).one()
        outbox_row = db.query(EventOutbox).filter(EventOutbox.event_type == AUTH_SMS_CODE_EVENT).one()
        assert refreshed.phone_number == "+17805550101"
        assert refreshed.phone_verified is False
        assert refreshed.phone_verified_at is None
        assert refreshed.sms_mfa_enabled is False
        assert sms_row.purpose == PHONE_VERIFICATION_PURPOSE
        assert sms_row.code_hash != _decrypt_sensitive_value(sms_row.code_encrypted)
        assert outbox_row.payload["sms_code_id"] == sms_row.user_sms_code_id
        assert "0101" in outbox_row.payload["phone_number_hint"]
    finally:
        db.close()


def test_phone_verification_confirm_marks_phone_verified_and_code_is_single_use():
    account = _seed_account(
        company_id=66134,
        username="phone-confirm-user",
        email="phone-confirm@example.com",
        password="PhoneConfirmPass#1",
    )
    headers = _auth_headers_from_login("phone-confirm-user", "PhoneConfirmPass#1", 66134)
    _start_phone_verification(headers, "+1 780 555 0102")
    _, code = _latest_sms_code(user_account_id=account.user_account_id, purpose=PHONE_VERIFICATION_PURPOSE)

    confirm = client.post(
        "/auth/phone/confirm-verification",
        headers=headers,
        json={"code": code},
    )

    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "phone_verified"

    reused = client.post(
        "/auth/phone/confirm-verification",
        headers=headers,
        json={"code": code},
    )
    assert reused.status_code == 400
    assert reused.json()["detail"]["code"] == "invalid_phone_verification_code"

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        assert refreshed.phone_verified is True
        assert refreshed.phone_verified_at is not None
        assert refreshed.sms_mfa_enabled is True
    finally:
        db.close()


def test_phone_verification_code_expiry_is_enforced():
    account = _seed_account(
        company_id=66135,
        username="phone-expiry-user",
        email="phone-expiry@example.com",
        password="PhoneExpiryPass#1",
    )
    headers = _auth_headers_from_login("phone-expiry-user", "PhoneExpiryPass#1", 66135)
    _start_phone_verification(headers, "+17805550103")
    row, code = _latest_sms_code(user_account_id=account.user_account_id, purpose=PHONE_VERIFICATION_PURPOSE)

    db = SessionLocal()
    try:
        persisted = db.query(UserSmsCode).filter(UserSmsCode.user_sms_code_id == row.user_sms_code_id).one()
        persisted.expires_at = persisted.created_at
        db.add(persisted)
        db.commit()
    finally:
        db.close()

    confirm = client.post(
        "/auth/phone/confirm-verification",
        headers=headers,
        json={"code": code},
    )
    assert confirm.status_code == 400
    assert confirm.json()["detail"]["code"] == "invalid_phone_verification_code"


def test_sms_mfa_login_step_up_succeeds_with_verified_phone():
    account = _seed_account(
        company_id=66136,
        username="sms-login-user",
        email="sms-login@example.com",
        password="SmsLoginPass#1",
    )
    headers = _auth_headers_from_login("sms-login-user", "SmsLoginPass#1", 66136)
    _start_phone_verification(headers, "+17805550104")
    _, verify_code = _latest_sms_code(user_account_id=account.user_account_id, purpose=PHONE_VERIFICATION_PURPOSE)
    confirm = client.post("/auth/phone/confirm-verification", headers=headers, json={"code": verify_code})
    assert confirm.status_code == 200, confirm.text
    _enable_mfa("sms-login-user", "SmsLoginPass#1", 66136)
    preference = client.post(
        "/auth/mfa/preference",
        headers=headers,
        json={"preferred_mfa_method": "sms", "sms_mfa_enabled": True},
    )
    assert preference.status_code == 200, preference.text
    assert preference.json()["preferred_mfa_method"] == "sms"

    login = _login("sms-login-user", "SmsLoginPass#1")
    assert login.status_code == 200, login.text
    assert "sms" in login.json()["available_mfa_methods"]
    assert login.json()["preferred_mfa_method"] == "sms"

    send_code = client.post(
        "/auth/mfa/send-sms-code",
        json={"challenge_token": login.json()["mfa_challenge_token"]},
    )
    assert send_code.status_code == 200, send_code.text
    assert send_code.json()["status"] == "sms_code_queued"

    _, code = _latest_sms_code(user_account_id=account.user_account_id, purpose=MFA_LOGIN_SMS_PURPOSE)
    complete = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login.json()["mfa_challenge_token"],
            "code": code,
            "method": "sms",
        },
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["access_token"]

    second_login = _login("sms-login-user", "SmsLoginPass#1")
    reused = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": second_login.json()["mfa_challenge_token"],
            "code": code,
            "method": "sms",
        },
    )
    assert reused.status_code == 401
    assert reused.json()["detail"]["code"] == "invalid_mfa_code"


def test_invalid_sms_mfa_code_is_rejected():
    account = _seed_account(
        company_id=66137,
        username="sms-invalid-user",
        email="sms-invalid@example.com",
        password="SmsInvalidPass#1",
    )
    headers = _auth_headers_from_login("sms-invalid-user", "SmsInvalidPass#1", 66137)
    _start_phone_verification(headers, "+17805550105")
    _, verify_code = _latest_sms_code(user_account_id=account.user_account_id, purpose=PHONE_VERIFICATION_PURPOSE)
    assert client.post("/auth/phone/confirm-verification", headers=headers, json={"code": verify_code}).status_code == 200
    _enable_mfa("sms-invalid-user", "SmsInvalidPass#1", 66137)

    login = _login("sms-invalid-user", "SmsInvalidPass#1")
    send_code = client.post("/auth/mfa/send-sms-code", json={"challenge_token": login.json()["mfa_challenge_token"]})
    assert send_code.status_code == 200, send_code.text

    complete = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login.json()["mfa_challenge_token"],
            "code": "000000",
            "method": "sms",
        },
    )
    assert complete.status_code == 401
    assert complete.json()["detail"]["code"] == "invalid_mfa_code"


def test_unverified_phone_cannot_be_used_for_sms_mfa():
    _seed_account(
        company_id=66138,
        username="sms-unverified-user",
        email="sms-unverified@example.com",
        password="SmsUnverifiedPass#1",
    )
    headers = _auth_headers_from_login("sms-unverified-user", "SmsUnverifiedPass#1", 66138)
    _start_phone_verification(headers, "+17805550106")
    _enable_mfa("sms-unverified-user", "SmsUnverifiedPass#1", 66138)

    login = _login("sms-unverified-user", "SmsUnverifiedPass#1")
    send_code = client.post("/auth/mfa/send-sms-code", json={"challenge_token": login.json()["mfa_challenge_token"]})
    assert send_code.status_code == 401
    assert send_code.json()["detail"]["code"] == "sms_mfa_unavailable"


def test_sms_mfa_company_and_user_isolation_is_preserved():
    account_a = _seed_account(
        company_id=66139,
        username="sms-isolation-a",
        email="sms-isolation-a@example.com",
        password="SmsIsolationPass#1",
    )
    account_b = _seed_account(
        company_id=66140,
        username="sms-isolation-b",
        email="sms-isolation-b@example.com",
        password="SmsIsolationPass#1",
    )

    headers_a = _auth_headers_from_login("sms-isolation-a", "SmsIsolationPass#1", 66139)
    _start_phone_verification(headers_a, "+17805550107")
    _, verify_code_a = _latest_sms_code(user_account_id=account_a.user_account_id, purpose=PHONE_VERIFICATION_PURPOSE)
    assert client.post("/auth/phone/confirm-verification", headers=headers_a, json={"code": verify_code_a}).status_code == 200
    _enable_mfa("sms-isolation-a", "SmsIsolationPass#1", 66139)

    headers_b = _auth_headers_from_login("sms-isolation-b", "SmsIsolationPass#1", 66140)
    _start_phone_verification(headers_b, "+17805550108")
    _, verify_code_b = _latest_sms_code(user_account_id=account_b.user_account_id, purpose=PHONE_VERIFICATION_PURPOSE)
    assert client.post("/auth/phone/confirm-verification", headers=headers_b, json={"code": verify_code_b}).status_code == 200
    _enable_mfa("sms-isolation-b", "SmsIsolationPass#1", 66140)

    login_a = _login("sms-isolation-a", "SmsIsolationPass#1")
    assert client.post("/auth/mfa/send-sms-code", json={"challenge_token": login_a.json()["mfa_challenge_token"]}).status_code == 200
    login_b = _login("sms-isolation-b", "SmsIsolationPass#1")
    assert client.post("/auth/mfa/send-sms-code", json={"challenge_token": login_b.json()["mfa_challenge_token"]}).status_code == 200
    _, code_b = _latest_sms_code(user_account_id=account_b.user_account_id, purpose=MFA_LOGIN_SMS_PURPOSE)

    cross = client.post(
        "/auth/mfa/complete-login",
        json={
            "challenge_token": login_a.json()["mfa_challenge_token"],
            "code": code_b,
            "method": "sms",
        },
    )
    assert cross.status_code == 401
    assert cross.json()["detail"]["code"] == "invalid_mfa_code"


def test_forgot_username_returns_safe_response_and_only_queues_for_verified_account():
    _seed_account(
        company_id=66103,
        username="forgot-username-user",
        email="forgot-username@example.com",
        password="ValidPass#1",
        email_verified=True,
    )

    existing = client.post("/auth/forgot-username", json={"email": "forgot-username@example.com"})
    missing = client.post("/auth/forgot-username", json={"email": "missing@example.com"})

    assert existing.status_code == 202
    assert missing.status_code == 202
    assert existing.json() == missing.json()

    db = SessionLocal()
    try:
        rows = db.query(EventOutbox).filter(EventOutbox.event_type == USERNAME_REMINDER_EVENT).all()
        assert len(rows) == 1
        assert rows[0].payload["to_email"] == "forgot-username@example.com"
        assert rows[0].payload["username"] == "forgot-username-user"
    finally:
        db.close()


def test_forgot_password_generates_token_and_reset_password_validates_token_and_clears_lockout():
    account = _seed_account(
        company_id=66104,
        username="forgot-password-user",
        email="forgot-password@example.com",
        password="OriginalPass#1",
    )

    _login("forgot-password-user", "bad-pass")
    _login("forgot-password-user", "bad-pass")
    locked = _login("forgot-password-user", "bad-pass")
    assert locked.status_code == 423

    forgot = client.post("/auth/forgot-password", json={"email": "forgot-password@example.com"})
    assert forgot.status_code == 202

    invalid = client.post("/auth/reset-password", json={"token": "invalid-token", "new_password": "BrandNewPass#2"})
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_reset_token"

    raw_token = _extract_link_token(PASSWORD_RESET_EVENT, "reset_link")
    reset = client.post("/auth/reset-password", json={"token": raw_token, "new_password": "BrandNewPass#2"})
    assert reset.status_code == 200, reset.text

    used_again = client.post("/auth/reset-password", json={"token": raw_token, "new_password": "AnotherPass#3"})
    assert used_again.status_code == 400
    assert used_again.json()["detail"]["code"] == "invalid_reset_token"

    login = _login("forgot-password-user", "BrandNewPass#2")
    assert login.status_code == 200

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        tokens = db.query(UserPasswordResetToken).filter(UserPasswordResetToken.user_account_id == account.user_account_id).all()
        unlock_tokens = db.query(UserAccountUnlockToken).filter(UserAccountUnlockToken.user_account_id == account.user_account_id).all()
        assert refreshed.failed_login_attempt_count == 0
        assert refreshed.lockout_until is None
        assert refreshed.password_changed_at.isoformat() == reset.json()["password_changed_at"]
        assert len(tokens) == 1
        assert tokens[0].used_at is not None
        assert unlock_tokens == []
    finally:
        db.close()

    old_login = _login("forgot-password-user", "OriginalPass#1")
    assert old_login.status_code == 401


def test_unlock_account_request_is_generic_and_creates_token_only_for_existing_account():
    account = _seed_account(
        company_id=66110,
        username="unlock-user",
        email="unlock@example.com",
        password="UnlockPass#1",
    )

    existing = client.post("/auth/unlock-account", json={"email": "unlock@example.com"})
    missing = client.post("/auth/unlock-account", json={"email": "missing-unlock@example.com"})

    assert existing.status_code == 202
    assert missing.status_code == 202
    assert existing.json() == missing.json()

    db = SessionLocal()
    try:
        outbox_rows = db.query(EventOutbox).filter(EventOutbox.event_type == ACCOUNT_UNLOCK_EVENT).all()
        unlock_tokens = (
            db.query(UserAccountUnlockToken)
            .filter(UserAccountUnlockToken.user_account_id == account.user_account_id)
            .all()
        )
        assert len(outbox_rows) == 1
        assert outbox_rows[0].payload["to_email"] == "unlock@example.com"
        assert len(unlock_tokens) == 1
        assert unlock_tokens[0].used_at is None
    finally:
        db.close()


def test_confirm_unlock_clears_lockout_and_enforces_one_time_use():
    account = _seed_account(
        company_id=66111,
        username="unlock-confirm-user",
        email="unlock-confirm@example.com",
        password="UnlockPass#1",
    )

    _login("unlock-confirm-user", "bad-pass")
    _login("unlock-confirm-user", "bad-pass")
    locked = _login("unlock-confirm-user", "bad-pass")
    assert locked.status_code == 423

    request = client.post("/auth/unlock-account", json={"email": "unlock-confirm@example.com"})
    assert request.status_code == 202

    raw_token = _extract_link_token(ACCOUNT_UNLOCK_EVENT, "unlock_link")
    confirm = client.post("/auth/confirm-unlock", json={"token": raw_token})
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "account_unlocked"

    again = client.post("/auth/confirm-unlock", json={"token": raw_token})
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "invalid_unlock_token"

    login = _login("unlock-confirm-user", "UnlockPass#1")
    assert login.status_code == 200

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        token_row = db.query(UserAccountUnlockToken).filter(UserAccountUnlockToken.user_account_id == account.user_account_id).one()
        assert refreshed.failed_login_attempt_count == 0
        assert refreshed.lockout_until is None
        assert token_row.used_at is not None
    finally:
        db.close()


def test_confirm_unlock_rejects_expired_token():
    account = _seed_account(
        company_id=66112,
        username="unlock-expired-user",
        email="unlock-expired@example.com",
        password="UnlockPass#1",
    )

    request = client.post("/auth/unlock-account", json={"email": "unlock-expired@example.com"})
    assert request.status_code == 202
    raw_token = _extract_link_token(ACCOUNT_UNLOCK_EVENT, "unlock_link")

    db = SessionLocal()
    try:
        token_row = db.query(UserAccountUnlockToken).filter(UserAccountUnlockToken.user_account_id == account.user_account_id).one()
        token_row.expires_at = token_row.created_at
        db.add(token_row)
        db.commit()
    finally:
        db.close()

    expired = client.post("/auth/confirm-unlock", json={"token": raw_token})
    assert expired.status_code == 400
    assert expired.json()["detail"]["code"] == "unlock_token_expired"


def test_password_reset_clears_lockout_and_invalidates_pending_unlock_tokens():
    account = _seed_account(
        company_id=66113,
        username="reset-unlock-user",
        email="reset-unlock@example.com",
        password="ResetUnlockPass#1",
    )

    _login("reset-unlock-user", "bad-pass")
    _login("reset-unlock-user", "bad-pass")
    locked = _login("reset-unlock-user", "bad-pass")
    assert locked.status_code == 423

    unlock_request = client.post("/auth/unlock-account", json={"email": "reset-unlock@example.com"})
    forgot = client.post("/auth/forgot-password", json={"email": "reset-unlock@example.com"})
    assert unlock_request.status_code == 202
    assert forgot.status_code == 202

    unlock_token = _extract_link_token(ACCOUNT_UNLOCK_EVENT, "unlock_link")
    reset_token = _extract_link_token(PASSWORD_RESET_EVENT, "reset_link")

    reset = client.post("/auth/reset-password", json={"token": reset_token, "new_password": "ResetUnlockPass#2"})
    assert reset.status_code == 200, reset.text

    unlock_after_reset = client.post("/auth/confirm-unlock", json={"token": unlock_token})
    assert unlock_after_reset.status_code == 400
    assert unlock_after_reset.json()["detail"]["code"] == "invalid_unlock_token"

    login = _login("reset-unlock-user", "ResetUnlockPass#2")
    assert login.status_code == 200

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        unlock_rows = db.query(UserAccountUnlockToken).filter(UserAccountUnlockToken.user_account_id == account.user_account_id).all()
        assert refreshed.failed_login_attempt_count == 0
        assert refreshed.lockout_until is None
        assert len(unlock_rows) == 1
        assert unlock_rows[0].used_at is not None
    finally:
        db.close()


def test_refresh_token_is_revoked_after_password_reset():
    account = _seed_account(
        company_id=66120,
        username="reset-refresh-user",
        email="reset-refresh@example.com",
        password="ResetRefreshPass#1",
    )

    login = _login("reset-refresh-user", "ResetRefreshPass#1")
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]

    refresh_before_reset = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_before_reset.status_code == 200, refresh_before_reset.text

    forgot = client.post("/auth/forgot-password", json={"email": "reset-refresh@example.com"})
    assert forgot.status_code == 202
    reset_token = _extract_link_token(PASSWORD_RESET_EVENT, "reset_link")

    reset = client.post("/auth/reset-password", json={"token": reset_token, "new_password": "ResetRefreshPass#2"})
    assert reset.status_code == 200, reset.text

    refresh_after_reset = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_after_reset.status_code == 401
    assert refresh_after_reset.json()["detail"]["code"] == "invalid_refresh_token"

    db = SessionLocal()
    try:
        rows = (
            db.query(UserRefreshToken)
            .filter(UserRefreshToken.user_account_id == account.user_account_id)
            .order_by(UserRefreshToken.created_at.asc())
            .all()
        )
        assert len(rows) == 2
        assert rows[0].revoked_at is not None
        assert rows[1].revoked_at is not None
    finally:
        db.close()


def test_refresh_token_is_revoked_after_authenticated_password_change():
    account = _seed_account(
        company_id=66121,
        username="change-refresh-user",
        email="change-refresh@example.com",
        password="ChangeRefreshPass#1",
    )

    login = _login("change-refresh-user", "ChangeRefreshPass#1")
    assert login.status_code == 200, login.text
    body = login.json()
    refresh_token = body["refresh_token"]

    refresh_before_change = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_before_change.status_code == 200, refresh_before_change.text

    change = client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {body['access_token']}", "X-Company-Id": "66121"},
        json={"current_password": "ChangeRefreshPass#1", "new_password": "ChangeRefreshPass#2"},
    )
    assert change.status_code == 200, change.text

    refresh_after_change = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_after_change.status_code == 401
    assert refresh_after_change.json()["detail"]["code"] == "invalid_refresh_token"

    db = SessionLocal()
    try:
        rows = (
            db.query(UserRefreshToken)
            .filter(UserRefreshToken.user_account_id == account.user_account_id)
            .order_by(UserRefreshToken.created_at.asc())
            .all()
        )
        assert len(rows) == 2
        assert rows[0].revoked_at is not None
        assert rows[1].revoked_at is not None
    finally:
        db.close()


def test_password_change_refresh_revocation_preserves_company_isolation():
    _seed_account(
        company_id=66122,
        username="change-isolation-a",
        email="change-isolation-a@example.com",
        password="ChangeIsolationPass#1",
    )
    account_b = _seed_account(
        company_id=66123,
        username="change-isolation-b",
        email="change-isolation-b@example.com",
        password="ChangeIsolationPass#1",
    )

    login_a = _login("change-isolation-a", "ChangeIsolationPass#1")
    login_b = _login("change-isolation-b", "ChangeIsolationPass#1")
    assert login_a.status_code == 200, login_a.text
    assert login_b.status_code == 200, login_b.text

    change_a = client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {login_a.json()['access_token']}", "X-Company-Id": "66122"},
        json={"current_password": "ChangeIsolationPass#1", "new_password": "ChangeIsolationPass#2"},
    )
    assert change_a.status_code == 200, change_a.text

    refresh_a = client.post("/auth/refresh", json={"refresh_token": login_a.json()["refresh_token"]})
    refresh_b = client.post("/auth/refresh", json={"refresh_token": login_b.json()["refresh_token"]})

    assert refresh_a.status_code == 401
    assert refresh_a.json()["detail"]["code"] == "invalid_refresh_token"
    assert refresh_b.status_code == 200, refresh_b.text
    assert verify_token(refresh_b.json()["access_token"])["company_id"] == 66123

    db = SessionLocal()
    try:
        rows = db.query(UserRefreshToken).filter(UserRefreshToken.user_account_id == account_b.user_account_id).all()
        assert len(rows) == 2
        assert sum(1 for row in rows if row.revoked_at is None) == 1
    finally:
        db.close()


def test_password_history_blocks_reuse_of_last_three_passwords_and_preserves_other_user():
    account_a = _seed_account(
        company_id=66105,
        username="history-user-a",
        email="history-a@example.com",
        password="HistoryPass#1",
    )
    _seed_account(
        company_id=66106,
        username="history-user-b",
        email="history-b@example.com",
        password="OtherUserPass#1",
    )

    for new_password in ["HistoryPass#2", "HistoryPass#3", "HistoryPass#4"]:
        forgot = client.post("/auth/forgot-password", json={"email": "history-a@example.com"})
        assert forgot.status_code == 202
        token = _extract_link_token(PASSWORD_RESET_EVENT, "reset_link")
        reset = client.post("/auth/reset-password", json={"token": token, "new_password": new_password})
        assert reset.status_code == 200, reset.text

    forgot = client.post("/auth/forgot-password", json={"email": "history-a@example.com"})
    assert forgot.status_code == 202
    token = _extract_link_token(PASSWORD_RESET_EVENT, "reset_link")
    reused = client.post("/auth/reset-password", json={"token": token, "new_password": "HistoryPass#2"})
    assert reused.status_code == 400
    assert reused.json()["detail"]["code"] == "password_reuse_not_allowed"

    other_user_login = _login("history-user-b", "OtherUserPass#1")
    assert other_user_login.status_code == 200

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account_a.user_account_id).one()
        assert refreshed.company_id == 66105
        assert refreshed.username == "history-user-a"
    finally:
        db.close()


def test_settings_security_profile_includes_account_security_state_and_company_tier():
    account = _seed_account(
        company_id=66107,
        username="settings-security-user",
        email="settings-security@example.com",
        password="SettingsPass#1",
    )

    login = _login("settings-security-user", "SettingsPass#1")
    assert login.status_code == 200
    token = login.json()["access_token"]
    response = client.get(
        "/settings/security-profile",
        headers={"Authorization": f"Bearer {token}", "X-Company-Id": "66107"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_account_id"] == account.user_account_id
    assert body["company_id"] == 66107
    assert body["selected_tier"] == "tier_3_full_system"
    assert body["role"] == "MANAGER"
    assert body["username"] == "settings-security-user"
    assert body["email"] == "settings-security@example.com"
    assert body["email_verified"] is True
    assert body["phone_number_hint"] is None
    assert body["has_phone_number"] is False
    assert body["phone_verified"] is False
    assert body["phone_verified_at"] is None
    assert body["mfa_enabled"] is False
    assert body["sms_mfa_enabled"] is False
    assert body["available_mfa_methods"] == []
    assert body["preferred_mfa_method"] is None


def test_settings_security_profile_returns_unverified_phone_state():
    account = _seed_account(
        company_id=66108,
        username="settings-mfa-state-user",
        email="settings-mfa-state@example.com",
        password="SettingsMfaPass#1",
    )
    headers = _auth_headers_from_login("settings-mfa-state-user", "SettingsMfaPass#1", 66108)

    start = _start_phone_verification(headers, "+17805550155")
    assert start["phone_number_hint"].endswith("0155")

    pending = client.get("/settings/security-profile", headers=headers)
    assert pending.status_code == 200, pending.text
    pending_body = pending.json()
    assert pending_body["phone_number_hint"].endswith("0155")
    assert pending_body["has_phone_number"] is True
    assert pending_body["phone_verified"] is False
    assert pending_body["phone_verified_at"] is None
    assert pending_body["mfa_enabled"] is False
    assert pending_body["sms_mfa_enabled"] is False
    assert pending_body["available_mfa_methods"] == []
    assert pending_body["preferred_mfa_method"] is None


def test_settings_security_profile_returns_verified_phone_with_sms_mfa_disabled():
    account = _seed_account(
        company_id=66109,
        username="settings-totp-only-user",
        email="settings-totp-only@example.com",
        password="SettingsTotpPass#1",
    )
    headers = _auth_headers_from_login("settings-totp-only-user", "SettingsTotpPass#1", 66109)

    start = _start_phone_verification(headers, "+17805550156")
    assert start["phone_number_hint"].endswith("0156")

    _, verify_code = _latest_sms_code(user_account_id=account.user_account_id, purpose=PHONE_VERIFICATION_PURPOSE)
    confirm = client.post("/auth/phone/confirm-verification", headers=headers, json={"code": verify_code})
    assert confirm.status_code == 200, confirm.text

    _enable_mfa("settings-totp-only-user", "SettingsTotpPass#1", 66109)
    disable_sms = client.post(
        "/auth/mfa/preference",
        headers=headers,
        json={"preferred_mfa_method": "totp", "sms_mfa_enabled": False},
    )
    assert disable_sms.status_code == 200, disable_sms.text

    totp_only = client.get("/settings/security-profile", headers=headers)
    assert totp_only.status_code == 200, totp_only.text
    totp_only_body = totp_only.json()
    assert totp_only_body["phone_number_hint"].endswith("0156")
    assert totp_only_body["has_phone_number"] is True
    assert totp_only_body["phone_verified"] is True
    assert totp_only_body["phone_verified_at"] is not None
    assert totp_only_body["mfa_enabled"] is True
    assert totp_only_body["sms_mfa_enabled"] is False
    assert totp_only_body["available_mfa_methods"] == ["totp"]
    assert totp_only_body["preferred_mfa_method"] == "totp"


def test_settings_security_profile_returns_verified_phone_with_sms_mfa_enabled():
    account = _seed_account(
        company_id=66110,
        username="settings-sms-enabled-user",
        email="settings-sms-enabled@example.com",
        password="SettingsSmsPass#1",
    )
    headers = _auth_headers_from_login("settings-sms-enabled-user", "SettingsSmsPass#1", 66110)

    start = _start_phone_verification(headers, "+17805550157")
    assert start["phone_number_hint"].endswith("0157")

    _, verify_code = _latest_sms_code(user_account_id=account.user_account_id, purpose=PHONE_VERIFICATION_PURPOSE)
    confirm = client.post("/auth/phone/confirm-verification", headers=headers, json={"code": verify_code})
    assert confirm.status_code == 200, confirm.text

    _enable_mfa("settings-sms-enabled-user", "SettingsSmsPass#1", 66110)

    enable_sms = client.post(
        "/auth/mfa/preference",
        headers=headers,
        json={"preferred_mfa_method": "sms", "sms_mfa_enabled": True},
    )
    assert enable_sms.status_code == 200, enable_sms.text

    sms_enabled = client.get("/settings/security-profile", headers=headers)
    assert sms_enabled.status_code == 200, sms_enabled.text
    sms_enabled_body = sms_enabled.json()
    assert sms_enabled_body["phone_number_hint"].endswith("0157")
    assert sms_enabled_body["has_phone_number"] is True
    assert sms_enabled_body["phone_verified"] is True
    assert sms_enabled_body["phone_verified_at"] is not None
    assert sms_enabled_body["mfa_enabled"] is True
    assert sms_enabled_body["sms_mfa_enabled"] is True
    assert sms_enabled_body["available_mfa_methods"] == ["totp", "sms"]
    assert sms_enabled_body["preferred_mfa_method"] == "sms"


def test_settings_security_profile_returns_canonical_preferred_method_when_multiple_methods_are_enabled():
    account = _seed_account(
        company_id=66111,
        username="settings-preferred-method-user",
        email="settings-preferred-method@example.com",
        password="SettingsPreferredPass#1",
    )
    headers = _auth_headers_from_login("settings-preferred-method-user", "SettingsPreferredPass#1", 66111)

    start = _start_phone_verification(headers, "+17805550158")
    assert start["phone_number_hint"].endswith("0158")

    _, verify_code = _latest_sms_code(user_account_id=account.user_account_id, purpose=PHONE_VERIFICATION_PURPOSE)
    confirm = client.post("/auth/phone/confirm-verification", headers=headers, json={"code": verify_code})
    assert confirm.status_code == 200, confirm.text

    _enable_mfa("settings-preferred-method-user", "SettingsPreferredPass#1", 66111)

    enable_sms = client.post(
        "/auth/mfa/preference",
        headers=headers,
        json={"preferred_mfa_method": "sms", "sms_mfa_enabled": True},
    )
    assert enable_sms.status_code == 200, enable_sms.text

    response = client.get("/settings/security-profile", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available_mfa_methods"] == ["totp", "sms"]
    assert body["preferred_mfa_method"] == "sms"


def test_invite_user_generates_token_and_complete_invite_creates_account():
    _seed_account(
        company_id=66108,
        username="owner-invite",
        email="owner-invite@example.com",
        password="OwnerPass#1",
        role="OWNER",
    )
    headers = _auth_headers_from_login("owner-invite", "OwnerPass#1", 66108)

    invite = client.post("/auth/invite-user", headers=headers, json={"email": "new-user@example.com", "role": "ADMIN"})
    assert invite.status_code == 202, invite.text

    raw_token = _extract_link_token(ACCOUNT_INVITE_EVENT, "invite_link")
    complete = client.post(
        "/auth/complete-invite",
        json={"token": raw_token, "username": "new-admin", "password": "WelcomePass#2"},
    )
    assert complete.status_code == 200, complete.text
    body = complete.json()
    assert body["company_id"] == 66108
    assert body["user_account_id"]

    login = _login("new-admin", "WelcomePass#2")
    assert login.status_code == 200

    db = SessionLocal()
    try:
        account = db.query(UserAccount).filter(UserAccount.user_account_id == body["user_account_id"]).one()
        token_row = db.query(UserInviteToken).filter(UserInviteToken.company_id == 66108).one()
        assert account.company_id == 66108
        assert account.email == "new-user@example.com"
        assert account.role == "ADMIN"
        assert token_row.used_at is not None
    finally:
        db.close()


def test_invite_token_expiry_and_one_time_use_are_enforced():
    _seed_account(
        company_id=66109,
        username="owner-expiry",
        email="owner-expiry@example.com",
        password="OwnerPass#1",
        role="OWNER",
    )
    headers = _auth_headers_from_login("owner-expiry", "OwnerPass#1", 66109)

    invite = client.post("/auth/invite-user", headers=headers, json={"email": "expired-user@example.com", "role": "MANAGER"})
    assert invite.status_code == 202
    raw_token = _extract_link_token(ACCOUNT_INVITE_EVENT, "invite_link")

    db = SessionLocal()
    try:
        token_row = db.query(UserInviteToken).filter(UserInviteToken.company_id == 66109).one()
        token_row.expires_at = token_row.created_at
        db.add(token_row)
        db.commit()
    finally:
        db.close()

    expired = client.post(
        "/auth/complete-invite",
        json={"token": raw_token, "username": "expired-user", "password": "WelcomePass#2"},
    )
    assert expired.status_code == 400
    assert expired.json()["detail"]["code"] == "invite_token_expired"

    reinvite = client.post("/auth/invite-user", headers=headers, json={"email": "expired-user@example.com", "role": "MANAGER"})
    assert reinvite.status_code == 202
    valid_token = _extract_link_token(ACCOUNT_INVITE_EVENT, "invite_link")
    complete = client.post(
        "/auth/complete-invite",
        json={"token": valid_token, "username": "valid-user", "password": "WelcomePass#3"},
    )
    assert complete.status_code == 200

    reused = client.post(
        "/auth/complete-invite",
        json={"token": valid_token, "username": "valid-user-2", "password": "WelcomePass#4"},
    )
    assert reused.status_code == 400
    assert reused.json()["detail"]["code"] == "invalid_invite_token"


def test_company_isolation_on_invite_flow_is_preserved():
    _seed_account(
        company_id=66110,
        username="owner-company-a",
        email="owner-company-a@example.com",
        password="OwnerPass#1",
        role="OWNER",
    )
    _seed_account(
        company_id=66111,
        username="owner-company-b",
        email="owner-company-b@example.com",
        password="OwnerPass#1",
        role="OWNER",
    )

    headers_a = _auth_headers_from_login("owner-company-a", "OwnerPass#1", 66110)
    headers_b = _auth_headers_from_login("owner-company-b", "OwnerPass#1", 66111)

    invite_a = client.post("/auth/invite-user", headers=headers_a, json={"email": "isolated-user@example.com", "role": "MANAGER"})
    assert invite_a.status_code == 202

    complete = client.post(
        "/auth/complete-invite",
        json={
            "token": _extract_link_token(ACCOUNT_INVITE_EVENT, "invite_link"),
            "username": "isolated-user",
            "password": "WelcomePass#2",
        },
    )
    assert complete.status_code == 200
    assert complete.json()["company_id"] == 66110

    duplicate_other_company = client.post(
        "/auth/invite-user",
        headers=headers_b,
        json={"email": "isolated-user@example.com", "role": "MANAGER"},
    )
    assert duplicate_other_company.status_code == 202

    db = SessionLocal()
    try:
        rows = db.query(EventOutbox).filter(EventOutbox.event_type == ACCOUNT_INVITE_EVENT).all()
        accounts = db.query(UserAccount).filter(UserAccount.email == "isolated-user@example.com").all()
        assert len(accounts) == 1
        assert accounts[0].company_id == 66110
        assert len(rows) == 1
    finally:
        db.close()


def test_authenticated_change_password_success_requires_current_password_and_blocks_recent_reuse():
    _seed_account(
        company_id=66112,
        username="change-password-user",
        email="change-password@example.com",
        password="ChangePass#1",
    )
    headers = _auth_headers_from_login("change-password-user", "ChangePass#1", 66112)

    wrong_current = client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": "wrong", "new_password": "ChangePass#2"},
    )
    assert wrong_current.status_code == 400
    assert wrong_current.json()["detail"]["code"] == "current_password_incorrect"

    change_1 = client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": "ChangePass#1", "new_password": "ChangePass#2"},
    )
    assert change_1.status_code == 200, change_1.text

    headers = _auth_headers_from_login("change-password-user", "ChangePass#2", 66112)
    change_2 = client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": "ChangePass#2", "new_password": "ChangePass#3"},
    )
    assert change_2.status_code == 200

    headers = _auth_headers_from_login("change-password-user", "ChangePass#3", 66112)
    change_3 = client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": "ChangePass#3", "new_password": "ChangePass#4"},
    )
    assert change_3.status_code == 200

    headers = _auth_headers_from_login("change-password-user", "ChangePass#4", 66112)
    reused = client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": "ChangePass#4", "new_password": "ChangePass#2"},
    )
    assert reused.status_code == 400
    assert reused.json()["detail"]["code"] == "password_reuse_not_allowed"

    login_old = _login("change-password-user", "ChangePass#1")
    assert login_old.status_code == 401
    login_latest = _login("change-password-user", "ChangePass#4")
    assert login_latest.status_code == 200

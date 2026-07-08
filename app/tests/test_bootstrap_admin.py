from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.company_profile import CompanyProfile
from app.models.event_outbox import EventOutbox
from app.models.user_account import UserAccount
from app.services.account_security_service import ACCOUNT_INVITE_EVENT, verify_password
from app.services.bootstrap_admin_service import bootstrap_owner_admin_account

client = TestClient(app)


def _clear_bootstrap_env(monkeypatch) -> None:
    for name in (
        "BOOTSTRAP_ADMIN_ENABLED",
        "BOOTSTRAP_ADMIN_USERNAME",
        "BOOTSTRAP_ADMIN_EMAIL",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "BOOTSTRAP_COMPANY_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def _extract_latest_invite_token() -> str:
    db = SessionLocal()
    try:
        row = (
            db.query(EventOutbox)
            .filter(EventOutbox.event_type == ACCOUNT_INVITE_EVENT)
            .order_by(EventOutbox.id.desc())
            .first()
        )
        assert row is not None
        values = parse_qs(urlparse(str(row.payload["invite_link"])).query).get("token") or []
        assert values
        return values[0]
    finally:
        db.close()


def test_bootstrap_admin_is_created_with_safe_dev_defaults_when_no_user_exists(monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    _clear_bootstrap_env(monkeypatch)

    result = bootstrap_owner_admin_account()

    assert result.status == "created"
    assert result.company_id == 1
    assert result.username == "owner"
    assert result.email == "owner@frontier.local"
    assert result.password == "ChangeMeDev#1"
    assert result.profile_created is True

    db = SessionLocal()
    try:
        account = db.query(UserAccount).one()
        profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == 1).one()
        assert account.company_id == 1
        assert account.role == "OWNER"
        assert account.email_verified is True
        assert account.password_hash != "ChangeMeDev#1"
        assert verify_password("ChangeMeDev#1", account.password_hash) is True
        assert profile.company_id == 1
        assert profile.onboarding_completed is True
        assert "jobs" in list(profile.enabled_modules or [])
    finally:
        db.close()


def test_bootstrap_admin_is_not_recreated_when_any_user_already_exists(monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    _clear_bootstrap_env(monkeypatch)

    created = bootstrap_owner_admin_account()
    skipped = bootstrap_owner_admin_account()

    assert created.status == "created"
    assert skipped.status == "skipped"
    assert skipped.reason == "existing_user_accounts_present"

    db = SessionLocal()
    try:
        assert db.query(UserAccount).count() == 1
        assert db.query(CompanyProfile).count() == 1
    finally:
        db.close()


def test_bootstrap_admin_is_not_created_in_production_by_default(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_ENABLED", "1")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "prod-owner")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "prod-owner@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "ProdOwnerPass#1")
    monkeypatch.setenv("BOOTSTRAP_COMPANY_ID", "77")

    result = bootstrap_owner_admin_account()

    assert result.status == "skipped"
    assert result.reason == "bootstrap_not_allowed"

    db = SessionLocal()
    try:
        assert db.query(UserAccount).count() == 0
        assert db.query(CompanyProfile).count() == 0
    finally:
        db.close()


def test_bootstrap_admin_authenticates_and_supports_security_invite_and_password_change(monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "dev-owner")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "dev-owner@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "DevOwnerPass#1")
    monkeypatch.setenv("BOOTSTRAP_COMPANY_ID", "66150")

    result = bootstrap_owner_admin_account()
    assert result.status == "created"

    login = client.post("/auth/login", json={"username": "dev-owner", "password": "DevOwnerPass#1"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Company-Id": "66150"}

    profile = client.get("/settings/security-profile", headers=headers)
    assert profile.status_code == 200, profile.text
    assert profile.json()["role"] == "OWNER"
    assert profile.json()["company_id"] == 66150

    invite = client.post(
        "/auth/invite-user",
        headers=headers,
        json={"email": "bootstrap-invite@example.com", "role": "ADMIN"},
    )
    assert invite.status_code == 202, invite.text

    complete = client.post(
        "/auth/complete-invite",
        json={
            "token": _extract_latest_invite_token(),
            "username": "bootstrap-admin-2",
            "password": "InvitePass#2",
        },
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["company_id"] == 66150

    change = client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": "DevOwnerPass#1", "new_password": "DevOwnerPass#2"},
    )
    assert change.status_code == 200, change.text

    relogin = client.post("/auth/login", json={"username": "dev-owner", "password": "DevOwnerPass#2"})
    assert relogin.status_code == 200, relogin.text


def test_bootstrap_admin_preserves_company_profile_linkage(monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "linked-owner")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "linked-owner@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "LinkedOwnerPass#1")
    monkeypatch.setenv("BOOTSTRAP_COMPANY_ID", "66151")

    result = bootstrap_owner_admin_account()
    assert result.status == "created"

    db = SessionLocal()
    try:
        account = db.query(UserAccount).filter(UserAccount.username == "linked-owner").one()
        profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == 66151).one()
        assert account.company_id == profile.company_id
        assert profile.company_name == "Frontier Dev Company 66151"
        assert profile.selected_tier == "tier_3_full_system"
        assert profile.onboarding_completed is True
        assert len(list(profile.enabled_modules or [])) > 0
    finally:
        db.close()

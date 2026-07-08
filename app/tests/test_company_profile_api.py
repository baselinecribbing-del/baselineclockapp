from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "test") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {token}"}


def test_company_profile_create_read_and_update_persists_primary_trade_and_modules():
    company_id = 61001

    create = client.put(
        "/company/profile",
        headers=_auth_headers(company_id),
        json={
            "company_name": "Northline Foundations Ltd.",
            "primary_trade": "Foundations",
            "country": "CA",
            "province_or_state": "AB",
            "selected_tier": "tier_3_full_system",
            "enabled_modules": ["foundations", "jobs", "payroll", "field", "credentials"],
            "onboarding_completed": False,
        },
    )
    assert create.status_code == 200
    created = create.json()
    assert created["company_id"] == company_id
    assert created["company_name"] == "Northline Foundations Ltd."
    assert created["primary_trade"] == "Foundations"
    assert created["country"] == "CA"
    assert created["province_or_state"] == "AB"
    assert created["selected_tier"] == "tier_3_full_system"
    assert created["enabled_modules"] == ["foundations", "jobs", "payroll", "field", "credentials"]
    assert created["onboarding_completed"] is False

    read = client.get("/company/profile", headers=_auth_headers(company_id))
    assert read.status_code == 200
    assert read.json() == created

    update = client.put(
        "/company/profile",
        headers=_auth_headers(company_id),
        json={
            "company_name": "Northline Foundations + Civil Ltd.",
            "primary_trade": "Excavation",
            "country": "CA",
            "province_or_state": "BC",
            "selected_tier": "tier_2_clock_in_payroll",
            "enabled_modules": ["payroll", "field", "field"],
            "onboarding_completed": True,
        },
    )
    assert update.status_code == 200
    updated = update.json()
    assert updated["company_id"] == company_id
    assert updated["company_name"] == "Northline Foundations + Civil Ltd."
    assert updated["primary_trade"] == "Excavation"
    assert updated["province_or_state"] == "BC"
    assert updated["selected_tier"] == "tier_2_clock_in_payroll"
    assert updated["enabled_modules"] == ["payroll", "field"]
    assert updated["onboarding_completed"] is True
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] >= created["updated_at"]


def test_company_entitlements_resolve_by_tier():
    company_id = 61002
    save = client.put(
        "/company/profile",
        headers=_auth_headers(company_id),
        json={
            "company_name": "QuickClock Contracting",
            "primary_trade": "Roofing",
            "country": "CA",
            "province_or_state": "SK",
            "selected_tier": "tier_2_clock_in_payroll",
            "enabled_modules": ["field", "payroll"],
            "onboarding_completed": False,
        },
    )
    assert save.status_code == 200

    entitlements = client.get("/company/entitlements", headers=_auth_headers(company_id))
    assert entitlements.status_code == 200
    body = entitlements.json()
    assert body["company_id"] == company_id
    assert body["selected_tier"] == "tier_2_clock_in_payroll"
    assert body["enabled_modules"] == ["payroll", "field"]
    assert body["entitled_modules"] == ["payroll", "field"]
    assert body["entitled_capabilities"] == ["field", "clock_in", "payroll", "employees"]


def test_company_profile_isolation_is_enforced():
    owner_company_id = 61003
    other_company_id = 61004

    create = client.put(
        "/company/profile",
        headers=_auth_headers(owner_company_id),
        json={
            "company_name": "Waste Route Systems",
            "primary_trade": "Waste Hauling",
            "country": "CA",
            "province_or_state": "AB",
            "selected_tier": "tier_1_clock_in",
            "enabled_modules": ["field"],
            "onboarding_completed": True,
        },
    )
    assert create.status_code == 200

    get_other = client.get("/company/profile", headers=_auth_headers(other_company_id))
    assert get_other.status_code == 200
    other_body = get_other.json()
    assert other_body["company_id"] == other_company_id
    assert other_body["company_name"] != "Waste Route Systems"
    assert other_body["selected_tier"] == "tier_3_full_system"

    mismatch_headers = _auth_headers(owner_company_id)
    mismatch_headers["X-Company-Id"] = str(other_company_id)
    mismatch = client.get("/company/profile", headers=mismatch_headers)
    assert mismatch.status_code == 403


def test_company_profile_rejects_invalid_module_for_tier():
    company_id = 61005
    bad = client.put(
        "/company/profile",
        headers=_auth_headers(company_id),
        json={
            "company_name": "Tier One Field Only",
            "primary_trade": "Concrete",
            "country": "CA",
            "province_or_state": "AB",
            "selected_tier": "tier_1_clock_in",
            "enabled_modules": ["field", "payroll"],
            "onboarding_completed": False,
        },
    )
    assert bad.status_code == 422
    assert "Modules not available for tier_1_clock_in" in bad.json()["detail"]


def test_company_profile_rejects_unknown_module_values():
    company_id = 61006
    bad = client.put(
        "/company/profile",
        headers=_auth_headers(company_id),
        json={
            "company_name": "Validation Test Co",
            "primary_trade": "Plumbing",
            "country": "CA",
            "province_or_state": "AB",
            "selected_tier": "tier_3_full_system",
            "enabled_modules": ["field", "unknown_module"],
            "onboarding_completed": False,
        },
    )
    assert bad.status_code == 422

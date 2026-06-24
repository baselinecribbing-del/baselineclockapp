from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.deps.entitlements import require_company_capability
from app.main import app

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "test") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {token}"}


def _save_profile(
    *,
    company_id: int,
    selected_tier: str,
    enabled_modules: list[str],
    primary_trade: str = "Foundations",
) -> None:
    resp = client.put(
        "/company/profile",
        headers=_auth_headers(company_id),
        json={
            "company_name": f"Company {company_id}",
            "primary_trade": primary_trade,
            "country": "CA",
            "province_or_state": "AB",
            "selected_tier": selected_tier,
            "enabled_modules": enabled_modules,
            "onboarding_completed": True,
        },
    )
    assert resp.status_code == 200, resp.text


def test_allowed_modules_can_access_protected_routes():
    company_id = 62001
    _save_profile(
        company_id=company_id,
        selected_tier="tier_3_full_system",
        enabled_modules=[
            "jobs",
            "payroll",
            "costing",
            "invoices",
            "foundations",
            "waste_bins",
            "field",
            "dispatch",
            "credentials",
        ],
    )
    headers = _auth_headers(company_id)

    assert client.get("/jobs", headers=headers).status_code == 200
    assert client.get("/payroll/runs", headers=headers).status_code == 200
    assert client.get(
        "/costing/ledger/totals",
        headers=headers,
        params={"date_start": "2026-01-01T00:00:00", "date_end": "2026-01-31T00:00:00"},
    ).status_code == 200
    assert client.get("/invoices", headers=headers).status_code == 200
    assert client.get("/company-modules", headers=headers).status_code == 200
    assert client.get("/waste-bin/service-requests", headers=headers).status_code == 200
    assert client.get("/waste_bins", headers=headers).status_code == 200
    assert client.get("/field/crew-board", headers=headers).status_code == 200
    assert client.get("/credentials/trade-types", headers=headers).status_code == 200


def test_disallowed_tier_module_is_blocked():
    company_id = 62002
    _save_profile(
        company_id=company_id,
        selected_tier="tier_1_clock_in",
        enabled_modules=["field"],
    )

    blocked = client.get("/payroll/runs", headers=_auth_headers(company_id))
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "module_not_enabled"


def test_disabled_module_is_blocked_even_on_full_tier():
    company_id = 62003
    _save_profile(
        company_id=company_id,
        selected_tier="tier_3_full_system",
        enabled_modules=["jobs", "payroll", "field"],
    )

    blocked = client.get("/invoices", headers=_auth_headers(company_id))
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "module_not_enabled"


def test_frontier_ai_entitlement_resolution_and_enforcement():
    protected_app = FastAPI()

    @protected_app.get("/frontier-ai", dependencies=[Depends(require_company_capability("frontier_ai"))])
    def frontier_ai_probe():
        return {"ok": True}

    protected_client = TestClient(protected_app)

    tier_two_company_id = 62004
    _save_profile(
        company_id=tier_two_company_id,
        selected_tier="tier_2_clock_in_payroll",
        enabled_modules=["field", "payroll"],
        primary_trade="Roofing",
    )
    tier_two_entitlements = client.get("/company/entitlements", headers=_auth_headers(tier_two_company_id))
    assert tier_two_entitlements.status_code == 200
    assert "frontier_ai" not in tier_two_entitlements.json()["entitled_capabilities"]

    tier_three_company_id = 62005
    _save_profile(
        company_id=tier_three_company_id,
        selected_tier="tier_3_full_system",
        enabled_modules=["jobs", "payroll", "field", "credentials"],
        primary_trade="Electrical",
    )
    tier_three_entitlements = client.get("/company/entitlements", headers=_auth_headers(tier_three_company_id))
    assert tier_three_entitlements.status_code == 200
    assert "frontier_ai" in tier_three_entitlements.json()["entitled_capabilities"]

    blocked = protected_client.get("/frontier-ai", headers=_auth_headers(tier_two_company_id))
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "capability_not_enabled"

    allowed = protected_client.get("/frontier-ai", headers=_auth_headers(tier_three_company_id))
    assert allowed.status_code == 200
    assert allowed.json() == {"ok": True}


def test_company_isolation_remains_enforced_on_protected_routes():
    owner_company_id = 62006
    other_company_id = 62007
    _save_profile(company_id=owner_company_id, selected_tier="tier_3_full_system", enabled_modules=["jobs"])
    _save_profile(company_id=other_company_id, selected_tier="tier_3_full_system", enabled_modules=["jobs"])

    create = client.post("/jobs", headers=_auth_headers(owner_company_id), json={"name": "Isolation Job"})
    assert create.status_code == 200
    job_id = create.json()["id"]

    get_other = client.get(f"/jobs/{job_id}", headers=_auth_headers(other_company_id))
    assert get_other.status_code == 404

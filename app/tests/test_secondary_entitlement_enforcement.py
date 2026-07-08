from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.job import Job
from app.models.scope import Scope
from app.models.company_profile import CompanyProfile

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "test") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {token}"}


def _save_profile(company_id: int, *, selected_tier: str, enabled_modules: list[str]) -> None:
    resp = client.put(
        "/company/profile",
        headers=_auth_headers(company_id),
        json={
            "company_name": f"Company {company_id}",
            "primary_trade": "Foundations",
            "country": "CA",
            "province_or_state": "AB",
            "selected_tier": selected_tier,
            "enabled_modules": enabled_modules,
            "onboarding_completed": True,
        },
    )
    assert resp.status_code == 200, resp.text


def _seed_job(company_id: int, name: str = "Docs Job") -> int:
    db = SessionLocal()
    try:
        row = Job(company_id=company_id, name=name, is_active=True)
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def _seed_scope(company_id: int, job_id: int, name: str = "Scope A") -> int:
    db = SessionLocal()
    try:
        row = Scope(company_id=company_id, job_id=job_id, name=name, is_active=True)
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def test_job_documents_route_is_guarded_with_stable_code():
    company_id = 63001
    _save_profile(company_id, selected_tier="tier_1_clock_in", enabled_modules=["field"])

    blocked = client.get("/job-documents/job-start-intakes", headers=_auth_headers(company_id))
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "module_not_enabled"


def test_scopes_route_is_guarded_and_company_isolation_remains_correct():
    owner_company_id = 63002
    other_company_id = 63003
    _save_profile(owner_company_id, selected_tier="tier_3_full_system", enabled_modules=["jobs"])
    _save_profile(other_company_id, selected_tier="tier_3_full_system", enabled_modules=["jobs"])
    _save_profile(63004, selected_tier="tier_1_clock_in", enabled_modules=["field"])

    job_id = _seed_job(owner_company_id, "Scoped Job")
    create = client.post("/scopes", headers=_auth_headers(owner_company_id), json={"job_id": job_id, "name": "Pad Prep"})
    assert create.status_code == 200
    scope_id = create.json()["id"]

    blocked = client.get("/scopes", headers=_auth_headers(63004))
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "module_not_enabled"

    other_get = client.get(f"/scopes/{scope_id}", headers=_auth_headers(other_company_id))
    assert other_get.status_code == 404


def test_command_center_secondary_surfaces_are_guarded():
    company_id = 63005
    _save_profile(company_id, selected_tier="tier_3_full_system", enabled_modules=["field"])
    headers = _auth_headers(company_id)

    core = client.get("/command-center/overview", headers=headers, params={"module_context": "core"})
    assert core.status_code == 200

    waste_bins = client.get("/command-center/overview", headers=headers, params={"module_context": "waste_bins"})
    assert waste_bins.status_code == 403
    assert waste_bins.json()["detail"]["code"] == "module_not_enabled"

    foundations = client.get("/command-center/overview", headers=headers, params={"module_context": "foundations"})
    assert foundations.status_code == 403
    assert foundations.json()["detail"]["code"] == "module_not_enabled"


def test_company_profile_required_code_is_consistent_on_secondary_surfaces():
    company_id = 63006
    headers = _auth_headers(company_id)

    db = SessionLocal()
    try:
        db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).delete()
        db.commit()
    finally:
        db.close()

    blocked_docs = client.get("/job-documents/job-start-intakes", headers=headers)
    assert blocked_docs.status_code == 403
    assert blocked_docs.json()["detail"]["code"] == "company_profile_required"

    blocked_scopes = client.get("/scopes", headers=headers)
    assert blocked_scopes.status_code == 403
    assert blocked_scopes.json()["detail"]["code"] == "company_profile_required"


def test_job_documents_allowed_when_jobs_enabled():
    company_id = 63007
    _save_profile(company_id, selected_tier="tier_3_full_system", enabled_modules=["jobs"])
    job_id = _seed_job(company_id, "Documented Job")

    listing = client.get(f"/job-documents/jobs/{job_id}/documents", headers=_auth_headers(company_id))
    assert listing.status_code == 200
    assert listing.json() == []

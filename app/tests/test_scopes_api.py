from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth_headers(company_id: int) -> dict:
    resp = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert isinstance(data, dict), f"token response not a JSON object: {data}"
    assert "access_token" in data, f"token response missing access_token: {data}"
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {data['access_token']}"}


def test_scopes_create_list_get_and_cross_company_isolation():
    company_1 = 13001
    company_2 = 13002

    create_job = client.post(
        "/jobs",
        headers=_auth_headers(company_1),
        json={"name": "Job B"},
    )
    assert create_job.status_code == 200
    job_id = create_job.json()["id"]

    create_scope = client.post(
        "/scopes",
        headers=_auth_headers(company_1),
        json={"job_id": job_id, "name": "Scope B"},
    )
    assert create_scope.status_code == 200
    created = create_scope.json()
    scope_id = created["id"]
    assert created["company_id"] == company_1
    assert created["job_id"] == job_id
    assert created["name"] == "Scope B"
    assert created["is_active"] is True

    listing = client.get("/scopes", headers=_auth_headers(company_1))
    assert listing.status_code == 200
    rows = listing.json()
    assert any(row["id"] == scope_id for row in rows)

    get_own = client.get(f"/scopes/{scope_id}", headers=_auth_headers(company_1))
    assert get_own.status_code == 200
    assert get_own.json()["id"] == scope_id

    get_other = client.get(f"/scopes/{scope_id}", headers=_auth_headers(company_2))
    assert get_other.status_code == 404

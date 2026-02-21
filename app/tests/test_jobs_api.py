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


def test_jobs_create_list_get_and_cross_company_isolation():
    company_1 = 12001
    company_2 = 12002

    create = client.post(
        "/jobs",
        headers=_auth_headers(company_1),
        json={"name": "Job A"},
    )
    assert create.status_code == 200
    created = create.json()
    job_id = created["id"]
    assert created["company_id"] == company_1
    assert created["name"] == "Job A"
    assert created["is_active"] is True

    listing = client.get("/jobs", headers=_auth_headers(company_1))
    assert listing.status_code == 200
    rows = listing.json()
    assert any(row["id"] == job_id for row in rows)

    get_own = client.get(f"/jobs/{job_id}", headers=_auth_headers(company_1))
    assert get_own.status_code == 200
    assert get_own.json()["id"] == job_id

    get_other = client.get(f"/jobs/{job_id}", headers=_auth_headers(company_2))
    assert get_other.status_code == 404

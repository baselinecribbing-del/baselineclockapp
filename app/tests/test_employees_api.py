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


def test_employees_create_list_get_and_cross_company_isolation():
    company_1 = 11001
    company_2 = 11002

    create = client.post(
        "/employees",
        headers=_auth_headers(company_1),
        json={"name": "Alice"},
    )
    assert create.status_code == 200
    created = create.json()
    employee_id = created["id"]
    assert created["company_id"] == company_1
    assert created["name"] == "Alice"
    assert created["is_active"] is True

    listing = client.get("/employees", headers=_auth_headers(company_1))
    assert listing.status_code == 200
    rows = listing.json()
    assert any(row["id"] == employee_id for row in rows)

    get_own = client.get(f"/employees/{employee_id}", headers=_auth_headers(company_1))
    assert get_own.status_code == 200
    assert get_own.json()["id"] == employee_id

    get_other = client.get(f"/employees/{employee_id}", headers=_auth_headers(company_2))
    assert get_other.status_code == 404

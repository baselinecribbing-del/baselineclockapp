import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def _mint_token(user_id="dev-user", company_id=1) -> str:
    # /auth/token requires JWT_SECRET
    os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest-only-0000000000000000")
    r = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]

def _headers(token: str, company_id=1) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}

def test_missing_authorization_header_401():
    r = client.post(
        "/time_entries/clock_in",
        json={"employee_id": 101, "job_id": 201, "scope_id": 301},
        headers={"X-Company-Id": "1"},
    )
    assert r.status_code == 401

def test_wrong_scheme_401():
    token = _mint_token()
    r = client.post(
        "/time_entries/clock_in",
        json={"employee_id": 101, "job_id": 201, "scope_id": 301},
        headers={"Authorization": f"Basic {token}", "X-Company-Id": "1"},
    )
    assert r.status_code == 401

def test_garbled_bearer_token_401():
    r = client.post(
        "/time_entries/clock_in",
        json={"employee_id": 101, "job_id": 201, "scope_id": 301},
        headers={"Authorization": "Bearer not-a-real-token", "X-Company-Id": "1"},
    )
    assert r.status_code == 401

def test_missing_company_header_403():
    token = _mint_token()
    r = client.post(
        "/time_entries/clock_in",
        json={"employee_id": 101, "job_id": 201, "scope_id": 301},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert "X-Company-Id" in r.text

def test_company_mismatch_403():
    token = _mint_token(company_id=1)
    r = client.post(
        "/time_entries/clock_in",
        json={"employee_id": 101, "job_id": 201, "scope_id": 301},
        headers=_headers(token, company_id=2),
    )
    assert r.status_code == 403
    assert "Company mismatch" in r.text

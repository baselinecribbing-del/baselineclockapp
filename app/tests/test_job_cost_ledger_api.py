from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.job_cost_ledger import JobCostLedger

client = TestClient(app)


def _auth_headers(company_id: int) -> dict:
    r = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    token = r.json()["access_token"]
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {token}"}


def _insert_row(company_id: int, job_id: int, source_reference_id: str):
    db = SessionLocal()
    try:
        row = JobCostLedger(
            company_id=company_id,
            job_id=job_id,
            scope_id=None,
            employee_id=None,
            source_type="LABOR",
            source_reference_id=source_reference_id,
            cost_category="LABOR_GROSS",
            quantity=None,
            unit_cost_cents=None,
            total_cost_cents=123,
            posting_date=datetime.utcnow(),
            immutable_flag=True,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def test_ledger_read_filters_by_company():
    ref1 = f"c1-{uuid4()}"
    ref2 = f"c2-{uuid4()}"
    company_1 = 7001
    company_2 = 7002
    job_id = 7101

    _insert_row(company_id=company_1, job_id=job_id, source_reference_id=ref1)
    _insert_row(company_id=company_2, job_id=job_id, source_reference_id=ref2)

    r1 = client.get(f"/costing/job/{job_id}/ledger", headers=_auth_headers(company_1))
    assert r1.status_code == 200
    data1 = r1.json()
    refs1 = [row["source_reference_id"] for row in data1["rows"]]
    assert ref1 in refs1
    assert ref2 not in refs1

    r2 = client.get(f"/costing/job/{job_id}/ledger", headers=_auth_headers(company_2))
    assert r2.status_code == 200
    data2 = r2.json()
    refs2 = [row["source_reference_id"] for row in data2["rows"]]
    assert ref2 in refs2
    assert ref1 not in refs2


def test_costing_requires_company_header():
    r = client.get("/costing/job/1/ledger")
    assert r.status_code == 401

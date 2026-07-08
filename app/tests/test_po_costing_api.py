from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_po(company_id: int, po_number: str) -> tuple[int, int, str]:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"PO Cost Job {po_number}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Scope {po_number}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=po_number,
            status="ISSUED",
        )
        db.add(po)
        db.commit()
        return int(job.id), int(scope.id), str(po.job_purchase_order_id)
    finally:
        db.close()


def test_purchase_order_cost_entry_creation_and_listing():
    company_id = 8101
    _job_id, _scope_id, po_id = _seed_po(company_id, "PO-COST-001")

    create = client.post(
        f"/job-documents/purchase-orders/{po_id}/costs",
        headers=_auth_headers(company_id),
        json={"amount_cents": 125000, "description": "Concrete supply invoice"},
    )
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["job_purchase_order_id"] == po_id
    assert created["amount_cents"] == 125000
    assert created["description"] == "Concrete supply invoice"

    listing = client.get(
        f"/job-documents/purchase-orders/{po_id}/costs",
        headers=_auth_headers(company_id),
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]


def test_purchase_order_cost_company_scoping_enforced():
    owner_company = 8201
    other_company = 8202
    _job_id, _scope_id, po_id = _seed_po(owner_company, "PO-COST-002")

    create_wrong_company = client.post(
        f"/job-documents/purchase-orders/{po_id}/costs",
        headers=_auth_headers(other_company),
        json={"amount_cents": 1000, "description": "Unauthorized post"},
    )
    assert create_wrong_company.status_code == 404, create_wrong_company.text

    list_wrong_company = client.get(
        f"/job-documents/purchase-orders/{po_id}/costs",
        headers=_auth_headers(other_company),
    )
    assert list_wrong_company.status_code == 404, list_wrong_company.text


def test_purchase_order_cost_idempotency_on_company_po_description():
    company_id = 8301
    _job_id, _scope_id, po_id = _seed_po(company_id, "PO-COST-003")

    payload = {"amount_cents": 99000, "description": "Rebar materials"}

    first = client.post(
        f"/job-documents/purchase-orders/{po_id}/costs",
        headers=_auth_headers(company_id),
        json=payload,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/job-documents/purchase-orders/{po_id}/costs",
        headers=_auth_headers(company_id),
        json=payload,
    )
    assert second.status_code == 200, second.text

    assert first.json()["id"] == second.json()["id"]

    listing = client.get(
        f"/job-documents/purchase-orders/{po_id}/costs",
        headers=_auth_headers(company_id),
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1


def test_purchase_order_costs_reconcile_in_ledger_totals_for_job():
    company_id = 8401
    job_id, _scope_id, po_id = _seed_po(company_id, "PO-COST-004")

    r1 = client.post(
        f"/job-documents/purchase-orders/{po_id}/costs",
        headers=_auth_headers(company_id),
        json={"amount_cents": 50000, "description": "Concrete"},
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        f"/job-documents/purchase-orders/{po_id}/costs",
        headers=_auth_headers(company_id),
        json={"amount_cents": 25000, "description": "Steel"},
    )
    assert r2.status_code == 200, r2.text

    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=1)).isoformat()
    end = (now + timedelta(days=1)).isoformat()

    totals = client.get(
        "/costing/ledger/totals",
        headers=_auth_headers(company_id),
        params={"date_start": start, "date_end": end, "job_id": job_id},
    )
    assert totals.status_code == 200, totals.text

    groups = totals.json()["groups"]
    assert len(groups) == 1
    assert groups[0]["job_id"] == job_id
    assert groups[0]["total_cost_cents"] == 75000
    assert groups[0]["row_count"] == 2

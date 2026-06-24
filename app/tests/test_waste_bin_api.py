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


def _seed_job_po(company_id: int, suffix: str) -> str:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"Waste Bin Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Waste Bin Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-WB-{suffix}",
            status="ISSUED",
        )
        db.add(po)
        db.commit()
        return str(po.job_purchase_order_id)
    finally:
        db.close()


def test_create_and_list_customer_sites_company_scoped():
    c1 = 9101
    c2 = 9102

    create = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(c1),
        json={
            "customer_name": "Acme Construction",
            "site_name": "Downtown Tower",
            "address_line_1": "100 Main St",
            "city": "Calgary",
            "province": "AB",
            "postal_code": "T1T1T1",
            "contact_name": "Alex",
            "contact_email": "alex@acme.example",
            "contact_phone": "555-0101",
        },
    )
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["company_id"] == c1

    c1_list = client.get("/waste-bin/customer-sites", headers=_auth_headers(c1))
    assert c1_list.status_code == 200, c1_list.text
    assert len(c1_list.json()) == 1

    c2_list = client.get("/waste-bin/customer-sites", headers=_auth_headers(c2))
    assert c2_list.status_code == 200, c2_list.text
    assert c2_list.json() == []


def test_create_and_list_assets_unique_bin_number_enforced_per_company():
    c1 = 9201
    c2 = 9202

    create_1 = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(c1),
        json={
            "bin_number": "BIN-100",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
        },
    )
    assert create_1.status_code == 200, create_1.text

    duplicate_same_company = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(c1),
        json={
            "bin_number": "BIN-100",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
        },
    )
    assert duplicate_same_company.status_code == 409, duplicate_same_company.text

    same_number_other_company = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(c2),
        json={
            "bin_number": "BIN-100",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
        },
    )
    assert same_number_other_company.status_code == 200, same_number_other_company.text

    list_available = client.get(
        "/waste-bin/assets",
        headers=_auth_headers(c1),
        params={"status": "AVAILABLE"},
    )
    assert list_available.status_code == 200, list_available.text
    assert len(list_available.json()) == 1


def test_create_and_list_bin_service_requests_with_status_filter_and_job_po_linkage():
    company_id = 9301
    other_company = 9302

    site = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": "City Builder",
            "site_name": "West Site",
            "address_line_1": "200 Market St",
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T2T2T2",
        },
    )
    assert site.status_code == 200, site.text
    site_id = site.json()["customer_site_id"]

    po_id = _seed_job_po(company_id, "REQ")

    create_open = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": "DROP",
            "request_notes": "Need initial drop",
        },
    )
    assert create_open.status_code == 200, create_open.text
    req_1 = create_open.json()
    assert req_1["job_purchase_order_id"] == po_id
    assert req_1["status"] == "OPEN"

    create_scheduled = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "request_type": "SWAP",
            "status": "SCHEDULED",
            "request_notes": "Swap tomorrow",
        },
    )
    assert create_scheduled.status_code == 200, create_scheduled.text

    list_open = client.get(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        params={"status": "OPEN", "job_purchase_order_id": po_id},
    )
    assert list_open.status_code == 200, list_open.text
    rows = list_open.json()
    assert len(rows) == 1
    assert rows[0]["request_type"] == "DROP"

    cross_company = client.get(
        "/waste-bin/service-requests",
        headers=_auth_headers(other_company),
    )
    assert cross_company.status_code == 200, cross_company.text
    assert cross_company.json() == []


def test_create_and_list_bin_service_tickets_with_status_filter_and_job_po_linkage():
    company_id = 9401

    site = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": "Site Ops",
            "address_line_1": "300 Industrial Rd",
            "city": "Red Deer",
            "province": "AB",
            "postal_code": "T3T3T3",
        },
    )
    assert site.status_code == 200, site.text
    site_id = site.json()["customer_site_id"]

    po_id = _seed_job_po(company_id, "TKT")

    asset = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(company_id),
        json={
            "bin_number": "BIN-9401",
            "bin_type": "ROLL_OFF",
            "bin_size": "30YD",
            "status": "AVAILABLE",
            "current_customer_site_id": site_id,
            "current_job_purchase_order_id": po_id,
        },
    )
    assert asset.status_code == 200, asset.text
    asset_id = asset.json()["bin_asset_id"]

    req = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": "PICKUP",
            "request_notes": "Pickup full bin",
        },
    )
    assert req.status_code == 200, req.text
    req_id = req.json()["bin_service_request_id"]

    ticket_open = client.post(
        "/waste-bin/service-tickets",
        headers=_auth_headers(company_id),
        json={
            "bin_service_request_id": req_id,
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "assigned_bin_asset_id": asset_id,
            "service_type": "PICKUP",
            "status": "OPEN",
        },
    )
    assert ticket_open.status_code == 200, ticket_open.text
    assert ticket_open.json()["job_purchase_order_id"] == po_id

    photo = client.post(
        f"/waste-bin/service-tickets/{ticket_open.json()['bin_service_ticket_id']}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": "PICKUP_PROOF",
            "storage_key": "placeholder://pickup-proof-9401",
            "captured_at": "2026-03-06T10:00:00Z",
        },
    )
    assert photo.status_code == 200, photo.text

    ticket_completed = client.post(
        f"/waste-bin/service-tickets/{ticket_open.json()['bin_service_ticket_id']}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "Completed on site"},
    )
    assert ticket_completed.status_code == 200, ticket_completed.text

    list_completed = client.get(
        "/waste-bin/service-tickets",
        headers=_auth_headers(company_id),
        params={"status": "COMPLETED"},
    )
    assert list_completed.status_code == 200, list_completed.text
    completed_rows = list_completed.json()
    assert len(completed_rows) == 1
    assert completed_rows[0]["status"] == "COMPLETED"

    list_by_po = client.get(
        "/waste-bin/service-tickets",
        headers=_auth_headers(company_id),
        params={"job_purchase_order_id": po_id},
    )
    assert list_by_po.status_code == 200, list_by_po.text
    assert len(list_by_po.json()) == 1

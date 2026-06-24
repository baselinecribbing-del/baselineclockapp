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
        job = Job(company_id=company_id, name=f"Waste Bin Completion Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Waste Bin Completion Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-WB-COMP-{suffix}",
            status="ISSUED",
        )
        db.add(po)
        db.commit()
        return str(po.job_purchase_order_id)
    finally:
        db.close()


def _create_site(company_id: int, address: str) -> str:
    resp = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": "Completion Site",
            "site_name": "Main",
            "address_line_1": address,
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T5T5T5",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["customer_site_id"])


def _create_ticket(company_id: int, service_type: str, suffix: str) -> str:
    site_id = _create_site(company_id=company_id, address=f"{suffix} Completion Way")
    po_id = _seed_job_po(company_id=company_id, suffix=suffix)

    req = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": service_type,
            "request_notes": f"Request {suffix}",
        },
    )
    assert req.status_code == 200, req.text

    ticket = client.post(
        "/waste-bin/service-tickets",
        headers=_auth_headers(company_id),
        json={
            "bin_service_request_id": req.json()["bin_service_request_id"],
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "service_type": service_type,
            "status": "OPEN",
        },
    )
    assert ticket.status_code == 200, ticket.text
    return str(ticket.json()["bin_service_ticket_id"])


def _add_photo(company_id: int, ticket_id: str, photo_type: str, key_suffix: str):
    return client.post(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": photo_type,
            "storage_key": f"placeholder://{key_suffix}",
            "captured_at": "2026-03-06T12:00:00Z",
            "captured_lat": 53.5461,
            "captured_lng": -113.4938,
        },
    )


def test_add_and_list_service_ticket_photos():
    company_id = 9601
    ticket_id = _create_ticket(company_id=company_id, service_type="DROP", suffix="A")

    add = _add_photo(company_id=company_id, ticket_id=ticket_id, photo_type="DROP_PROOF", key_suffix="drop-proof-A")
    assert add.status_code == 200, add.text
    photo = add.json()
    assert photo["bin_service_ticket_id"] == ticket_id
    assert photo["photo_type"] == "DROP_PROOF"

    listing = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["storage_key"] == "placeholder://drop-proof-A"


def test_complete_drop_ticket_with_drop_proof_succeeds():
    company_id = 9602
    ticket_id = _create_ticket(company_id=company_id, service_type="DROP", suffix="B")
    _add_photo(company_id=company_id, ticket_id=ticket_id, photo_type="DROP_PROOF", key_suffix="drop-proof-B")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "Drop complete"},
    )
    assert complete.status_code == 200, complete.text
    row = complete.json()
    assert row["status"] == "COMPLETED"
    assert row["completed_at"] is not None
    assert row["completed_by_user_id"] == "test-user"


def test_complete_swap_ticket_with_swap_proof_succeeds():
    company_id = 9603
    ticket_id = _create_ticket(company_id=company_id, service_type="SWAP", suffix="C")
    _add_photo(company_id=company_id, ticket_id=ticket_id, photo_type="SWAP_PROOF", key_suffix="swap-proof-C")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "Swap complete"},
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "COMPLETED"


def test_complete_pickup_ticket_with_pickup_proof_succeeds():
    company_id = 9604
    ticket_id = _create_ticket(company_id=company_id, service_type="PICKUP", suffix="D")
    _add_photo(company_id=company_id, ticket_id=ticket_id, photo_type="PICKUP_PROOF", key_suffix="pickup-proof-D")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "Pickup complete"},
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "COMPLETED"


def test_completion_without_required_proof_fails_with_409():
    company_id = 9605
    ticket_id = _create_ticket(company_id=company_id, service_type="DROP", suffix="E")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "Should fail"},
    )
    assert complete.status_code == 409, complete.text
    assert "DROP_PROOF" in complete.json()["detail"]


def test_double_completion_fails_with_409():
    company_id = 9606
    ticket_id = _create_ticket(company_id=company_id, service_type="SWAP", suffix="F")
    _add_photo(company_id=company_id, ticket_id=ticket_id, photo_type="SWAP_PROOF", key_suffix="swap-proof-F")

    first = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "First completion"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "Second completion"},
    )
    assert second.status_code == 409, second.text


def test_company_scoping_enforced_for_ticket_photo_and_completion_endpoints():
    company_id = 9607
    other_company = 9608
    ticket_id = _create_ticket(company_id=company_id, service_type="PICKUP", suffix="G")

    own_add = _add_photo(company_id=company_id, ticket_id=ticket_id, photo_type="PICKUP_PROOF", key_suffix="pickup-proof-G")
    assert own_add.status_code == 200, own_add.text

    other_add = _add_photo(
        company_id=other_company,
        ticket_id=ticket_id,
        photo_type="PICKUP_PROOF",
        key_suffix="pickup-proof-other",
    )
    assert other_add.status_code == 404, other_add.text

    other_list = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(other_company),
    )
    assert other_list.status_code == 404, other_list.text

    other_complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(other_company),
        json={"completion_notes": "not allowed"},
    )
    assert other_complete.status_code == 404, other_complete.text

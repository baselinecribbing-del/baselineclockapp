from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.landfill_trip import LandfillTrip
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
        job = Job(company_id=company_id, name=f"Waste Bin Landfill Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Waste Bin Landfill Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-WB-LANDFILL-{suffix}",
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
            "customer_name": "Landfill Site",
            "site_name": "Main",
            "address_line_1": address,
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T7T7T7",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["customer_site_id"])


def _create_completed_ticket(company_id: int, suffix: str, service_type: str = "PICKUP") -> tuple[str, str]:
    site_id = _create_site(company_id=company_id, address=f"{suffix} Landfill Way")
    po_id = _seed_job_po(company_id=company_id, suffix=suffix)

    asset = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(company_id),
        json={
            "bin_number": f"BIN-LF-{suffix}",
            "bin_type": "ROLL_OFF",
            "bin_size": "30YD",
            "status": "AVAILABLE",
            "current_customer_site_id": site_id,
            "current_job_purchase_order_id": po_id,
        },
    )
    assert asset.status_code == 200, asset.text

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
            "assigned_bin_asset_id": asset.json()["bin_asset_id"],
            "service_type": service_type,
            "status": "OPEN",
        },
    )
    assert ticket.status_code == 200, ticket.text
    ticket_id = str(ticket.json()["bin_service_ticket_id"])

    proof_type = {"DROP": "DROP_PROOF", "SWAP": "SWAP_PROOF", "PICKUP": "PICKUP_PROOF"}[service_type]
    proof = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": proof_type,
            "storage_key": f"placeholder://proof-{suffix}",
            "captured_at": "2026-03-06T12:00:00Z",
        },
    )
    assert proof.status_code == 200, proof.text

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": f"completed {suffix}"},
    )
    assert complete.status_code == 200, complete.text

    return ticket_id, str(asset.json()["bin_asset_id"])


def _add_receipt_photo(company_id: int, ticket_id: str, suffix: str) -> str:
    receipt = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": "RECEIPT",
            "storage_key": f"placeholder://receipt-{suffix}",
            "captured_at": "2026-03-06T15:00:00Z",
        },
    )
    assert receipt.status_code == 200, receipt.text
    return str(receipt.json()["bin_service_photo_id"])


def test_create_landfill_trip_and_list(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_COST_PER_KM_CENTS", "100")

    company_id = 9701
    ticket_id, asset_id = _create_completed_ticket(company_id=company_id, suffix="A", service_type="PICKUP")
    receipt_photo_id = _add_receipt_photo(company_id=company_id, ticket_id=ticket_id, suffix="A")

    create = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/landfill-trips",
        headers=_auth_headers(company_id),
        json={
            "bin_asset_id": asset_id,
            "dump_site_name": "Example Landfill",
            "dump_cost_cents": 12500,
            "km_driven": 32,
            "receipt_photo_id": receipt_photo_id,
        },
    )
    assert create.status_code == 200, create.text
    trip = create.json()
    assert trip["bin_service_ticket_id"] == ticket_id
    assert trip["bin_asset_id"] == asset_id
    assert trip["receipt_photo_id"] == receipt_photo_id

    listing = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/landfill-trips",
        headers=_auth_headers(company_id),
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["landfill_trip_id"] == trip["landfill_trip_id"]


def test_ticket_must_be_completed_to_record_landfill_trip():
    company_id = 9702
    site_id = _create_site(company_id=company_id, address="9702 Road")
    po_id = _seed_job_po(company_id=company_id, suffix="B")

    asset = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(company_id),
        json={
            "bin_number": "BIN-LF-B",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
            "current_customer_site_id": site_id,
            "current_job_purchase_order_id": po_id,
        },
    )
    assert asset.status_code == 200, asset.text

    req = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": "PICKUP",
            "request_notes": "not completed",
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
            "assigned_bin_asset_id": asset.json()["bin_asset_id"],
            "service_type": "PICKUP",
            "status": "OPEN",
        },
    )
    assert ticket.status_code == 200, ticket.text

    create = client.post(
        f"/waste-bin/service-tickets/{ticket.json()['bin_service_ticket_id']}/landfill-trips",
        headers=_auth_headers(company_id),
        json={
            "bin_asset_id": asset.json()["bin_asset_id"],
            "dump_site_name": "Example Landfill",
            "dump_cost_cents": 10000,
            "km_driven": 10,
        },
    )
    assert create.status_code == 409, create.text


def test_dump_and_km_cost_ledger_entries_created(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_COST_PER_KM_CENTS", "150")

    company_id = 9703
    ticket_id, asset_id = _create_completed_ticket(company_id=company_id, suffix="C", service_type="DROP")

    create = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/landfill-trips",
        headers=_auth_headers(company_id),
        json={
            "bin_asset_id": asset_id,
            "dump_site_name": "North Landfill",
            "dump_cost_cents": 22000,
            "km_driven": 20,
        },
    )
    assert create.status_code == 200, create.text
    trip_id = create.json()["landfill_trip_id"]

    db = SessionLocal()
    try:
        rows = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.source_type == "landfill_trip")
            .filter(JobCostLedger.source_reference_id.like(f"landfill_trip:{trip_id}:%"))
            .order_by(JobCostLedger.source_reference_id.asc())
            .all()
        )
        assert len(rows) == 2

        dump_row = next(r for r in rows if r.cost_category == "dump_cost")
        km_row = next(r for r in rows if r.cost_category == "vehicle_km")

        assert int(dump_row.total_cost_cents) == 22000
        assert int(km_row.unit_cost_cents) == 150
        assert int(km_row.total_cost_cents) == 3000
    finally:
        db.close()


def test_company_scoping_enforced_for_landfill_trip_endpoints():
    company_id = 9704
    other_company = 9705
    ticket_id, asset_id = _create_completed_ticket(company_id=company_id, suffix="D", service_type="SWAP")

    create_wrong = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/landfill-trips",
        headers=_auth_headers(other_company),
        json={
            "bin_asset_id": asset_id,
            "dump_site_name": "West Landfill",
            "dump_cost_cents": 10000,
            "km_driven": 5,
        },
    )
    assert create_wrong.status_code == 404, create_wrong.text

    list_wrong = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/landfill-trips",
        headers=_auth_headers(other_company),
    )
    assert list_wrong.status_code == 404, list_wrong.text


def test_receipt_photo_linkage_and_duplicate_trip_guard():
    company_id = 9706
    ticket_id, asset_id = _create_completed_ticket(company_id=company_id, suffix="E", service_type="PICKUP")
    receipt_photo_id = _add_receipt_photo(company_id=company_id, ticket_id=ticket_id, suffix="E")

    first = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/landfill-trips",
        headers=_auth_headers(company_id),
        json={
            "bin_asset_id": asset_id,
            "dump_site_name": "South Landfill",
            "dump_cost_cents": 18000,
            "km_driven": 17,
            "receipt_photo_id": receipt_photo_id,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["receipt_photo_id"] == receipt_photo_id

    second = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/landfill-trips",
        headers=_auth_headers(company_id),
        json={
            "bin_asset_id": asset_id,
            "dump_site_name": "South Landfill",
            "dump_cost_cents": 18000,
            "km_driven": 17,
            "receipt_photo_id": receipt_photo_id,
        },
    )
    assert second.status_code == 409, second.text

    db = SessionLocal()
    try:
        count = (
            db.query(LandfillTrip)
            .filter(LandfillTrip.company_id == company_id)
            .filter(LandfillTrip.bin_service_ticket_id == ticket_id)
            .count()
        )
        assert count == 1
    finally:
        db.close()

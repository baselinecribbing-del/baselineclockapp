from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
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
        job = Job(company_id=company_id, name=f"Waste Bin Track Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Waste Bin Track Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-WB-TRACK-{suffix}",
            status="ISSUED",
        )
        db.add(po)
        db.commit()
        return str(po.job_purchase_order_id)
    finally:
        db.close()


def _create_site(company_id: int, suffix: str) -> str:
    resp = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": f"Builder {suffix}",
            "site_name": "Main",
            "address_line_1": f"{suffix} Logistics Rd",
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T1A1A1",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["customer_site_id"])


def _request_type_for_service_type(service_type: str) -> str:
    mapping = {
        "DROP": "DROP",
        "DROP_BIN": "DROP",
        "SWAP": "SWAP",
        "SWAP_BIN": "SWAP",
        "PICKUP": "PICKUP",
        "PICKUP_BIN": "PICKUP",
        "LANDFILL_DUMP": "PICKUP",
    }
    return mapping[service_type]


def _create_ticket(company_id: int, suffix: str, service_type: str) -> tuple[str, str]:
    site_id = _create_site(company_id, suffix)
    po_id = _seed_job_po(company_id, suffix)

    req = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": _request_type_for_service_type(service_type),
            "request_notes": "tracking",
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
    return str(ticket.json()["bin_service_ticket_id"]), site_id


def _add_required_proof_if_needed(company_id: int, ticket_id: str, service_type: str) -> None:
    proof_by_type = {
        "DROP": "DROP_PROOF",
        "DROP_BIN": "DROP_PROOF",
        "SWAP": "SWAP_PROOF",
        "SWAP_BIN": "SWAP_PROOF",
        "PICKUP": "PICKUP_PROOF",
        "PICKUP_BIN": "PICKUP_PROOF",
    }
    proof = proof_by_type.get(service_type)
    if proof is None:
        return

    resp = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": proof,
            "storage_key": f"placeholder://{ticket_id}-{proof}",
            "captured_at": "2026-03-06T14:00:00Z",
        },
    )
    assert resp.status_code == 200, resp.text


def test_waste_bin_creation_and_company_scoping():
    c1 = 9951
    c2 = 9952

    created = client.post(
        "/waste_bins",
        headers=_auth_headers(c1),
        json={
            "bin_number": "WB-100",
            "capacity_yards": 20,
            "status": "AVAILABLE",
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["company_id"] == c1
    bin_id = row["id"]

    c1_list = client.get("/waste_bins", headers=_auth_headers(c1))
    assert c1_list.status_code == 200, c1_list.text
    assert len(c1_list.json()) == 1

    c2_list = client.get("/waste_bins", headers=_auth_headers(c2))
    assert c2_list.status_code == 200, c2_list.text
    assert c2_list.json() == []

    get_c1 = client.get(f"/waste_bins/{bin_id}", headers=_auth_headers(c1))
    assert get_c1.status_code == 200, get_c1.text

    get_c2 = client.get(f"/waste_bins/{bin_id}", headers=_auth_headers(c2))
    assert get_c2.status_code == 404, get_c2.text


def test_waste_bin_status_transitions_and_invalid_transition_rejected():
    company_id = 9953

    created = client.post(
        "/waste_bins",
        headers=_auth_headers(company_id),
        json={
            "bin_number": "WB-200",
            "capacity_yards": 30,
            "status": "AVAILABLE",
        },
    )
    assert created.status_code == 200, created.text
    bin_id = created.json()["id"]

    to_on_site = client.patch(
        f"/waste_bins/{bin_id}",
        headers=_auth_headers(company_id),
        json={"status": "ON_SITE"},
    )
    assert to_on_site.status_code == 200, to_on_site.text
    assert to_on_site.json()["status"] == "ON_SITE"

    invalid = client.patch(
        f"/waste_bins/{bin_id}",
        headers=_auth_headers(company_id),
        json={"status": "AT_LANDFILL"},
    )
    assert invalid.status_code == 409, invalid.text


def test_waste_bin_assignment_to_active_ticket_and_conflict_guard():
    company_id = 9954

    t1, _site_id = _create_ticket(company_id=company_id, suffix="A", service_type="DROP_BIN")
    t2, _site_id2 = _create_ticket(company_id=company_id, suffix="B", service_type="PICKUP_BIN")

    created = client.post(
        "/waste_bins",
        headers=_auth_headers(company_id),
        json={
            "bin_number": "WB-300",
            "capacity_yards": 40,
            "status": "IN_TRANSIT",
            "current_ticket_id": t1,
        },
    )
    assert created.status_code == 200, created.text
    bin_id = created.json()["id"]

    conflict = client.patch(
        f"/waste_bins/{bin_id}",
        headers=_auth_headers(company_id),
        json={"current_ticket_id": t2},
    )
    assert conflict.status_code == 409, conflict.text
    assert "active ticket" in conflict.json()["detail"]


def test_service_ticket_completion_updates_waste_bin_status_by_ticket_type(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_DROP_CENTS", "10000")
    monkeypatch.setenv("WASTE_BIN_PRICE_PICKUP_CENTS", "9000")

    company_id = 9955

    drop_ticket, drop_site_id = _create_ticket(company_id=company_id, suffix="C", service_type="DROP_BIN")
    drop_bin = client.post(
        "/waste_bins",
        headers=_auth_headers(company_id),
        json={
            "bin_number": "WB-400",
            "capacity_yards": 20,
            "status": "IN_TRANSIT",
            "current_ticket_id": drop_ticket,
        },
    )
    assert drop_bin.status_code == 200, drop_bin.text
    drop_bin_id = drop_bin.json()["id"]
    _add_required_proof_if_needed(company_id, drop_ticket, "DROP_BIN")

    complete_drop = client.post(
        f"/waste-bin/service-tickets/{drop_ticket}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "drop done"},
    )
    assert complete_drop.status_code == 200, complete_drop.text

    drop_after = client.get(f"/waste_bins/{drop_bin_id}", headers=_auth_headers(company_id))
    assert drop_after.status_code == 200, drop_after.text
    assert drop_after.json()["status"] == "ON_SITE"
    assert drop_after.json()["current_site_id"] == drop_site_id
    assert drop_after.json()["current_ticket_id"] is None

    pickup_ticket, _pickup_site_id = _create_ticket(company_id=company_id, suffix="D", service_type="PICKUP_BIN")
    pickup_bin = client.post(
        "/waste_bins",
        headers=_auth_headers(company_id),
        json={
            "bin_number": "WB-401",
            "capacity_yards": 20,
            "status": "ON_SITE",
            "current_site_id": drop_site_id,
            "current_ticket_id": pickup_ticket,
        },
    )
    assert pickup_bin.status_code == 200, pickup_bin.text
    pickup_bin_id = pickup_bin.json()["id"]
    _add_required_proof_if_needed(company_id, pickup_ticket, "PICKUP_BIN")

    complete_pickup = client.post(
        f"/waste-bin/service-tickets/{pickup_ticket}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "pickup done"},
    )
    assert complete_pickup.status_code == 200, complete_pickup.text

    pickup_after = client.get(f"/waste_bins/{pickup_bin_id}", headers=_auth_headers(company_id))
    assert pickup_after.status_code == 200, pickup_after.text
    assert pickup_after.json()["status"] == "IN_TRANSIT"
    assert pickup_after.json()["current_site_id"] is None

    dump_ticket, _dump_site_id = _create_ticket(company_id=company_id, suffix="E", service_type="LANDFILL_DUMP")
    dump_bin = client.post(
        "/waste_bins",
        headers=_auth_headers(company_id),
        json={
            "bin_number": "WB-402",
            "capacity_yards": 20,
            "status": "AT_LANDFILL",
            "current_ticket_id": dump_ticket,
        },
    )
    assert dump_bin.status_code == 200, dump_bin.text
    dump_bin_id = dump_bin.json()["id"]

    complete_dump = client.post(
        f"/waste-bin/service-tickets/{dump_ticket}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "dump done"},
    )
    assert complete_dump.status_code == 200, complete_dump.text

    dump_after = client.get(f"/waste_bins/{dump_bin_id}", headers=_auth_headers(company_id))
    assert dump_after.status_code == 200, dump_after.text
    assert dump_after.json()["status"] == "AVAILABLE"
    assert dump_after.json()["current_site_id"] is None

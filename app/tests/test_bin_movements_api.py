from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.bin_movement import BinMovement
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
        job = Job(company_id=company_id, name=f"Bin Movement Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Bin Movement Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-BM-{suffix}",
            status="ISSUED",
        )
        db.add(po)
        db.commit()
        return str(po.job_purchase_order_id)
    finally:
        db.close()


def _request_type_for_service_type(service_type: str) -> str:
    mapping = {
        "DROP_BIN": "DROP",
        "SWAP_BIN": "SWAP",
        "PICKUP": "PICKUP",
    }
    return mapping[service_type]


def _create_site(company_id: int, suffix: str) -> str:
    resp = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": f"Customer {suffix}",
            "site_name": f"Site {suffix}",
            "address_line_1": f"{suffix} Movement Rd",
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T5M5M5",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["customer_site_id"])


def _create_asset(company_id: int, suffix: str, site_id: str, po_id: str) -> str:
    resp = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(company_id),
        json={
            "bin_number": f"BIN-MV-{suffix}",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
            "current_customer_site_id": site_id,
            "current_job_purchase_order_id": po_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["bin_asset_id"])


def _create_ticket(company_id: int, suffix: str, service_type: str) -> tuple[str, str, str]:
    site_id = _create_site(company_id=company_id, suffix=suffix)
    po_id = _seed_job_po(company_id=company_id, suffix=suffix)
    asset_id = _create_asset(company_id=company_id, suffix=suffix, site_id=site_id, po_id=po_id)

    req = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": _request_type_for_service_type(service_type),
            "request_notes": "movement test",
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
            "assigned_bin_asset_id": asset_id,
            "service_type": service_type,
            "status": "OPEN",
        },
    )
    assert ticket.status_code == 200, ticket.text
    return str(ticket.json()["bin_service_ticket_id"]), asset_id, site_id


def _add_proof(company_id: int, ticket_id: str, photo_type: str) -> None:
    resp = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": photo_type,
            "storage_key": f"placeholder://{ticket_id}-{photo_type}",
            "captured_at": "2026-03-07T12:00:00Z",
        },
    )
    assert resp.status_code == 200, resp.text


def _complete_ticket(company_id: int, ticket_id: str) -> None:
    resp = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "completed"},
    )
    assert resp.status_code == 200, resp.text


def test_movement_created_when_drop_bin_ticket_completes():
    company_id = 9801
    ticket_id, asset_id, site_id = _create_ticket(company_id=company_id, suffix="DROP", service_type="DROP_BIN")
    _add_proof(company_id=company_id, ticket_id=ticket_id, photo_type="DROP_PROOF")

    _complete_ticket(company_id=company_id, ticket_id=ticket_id)

    history = client.get(f"/waste-bin/bins/{asset_id}/history", headers=_auth_headers(company_id))
    assert history.status_code == 200, history.text
    rows = history.json()
    assert len(rows) == 1
    assert rows[0]["movement_type"] == "DROP"
    assert rows[0]["to_location_type"] == "SITE"
    assert rows[0]["to_location_id"] == site_id
    assert rows[0]["related_ticket_id"] == ticket_id


def test_movement_created_when_swap_bin_ticket_completes():
    company_id = 9802
    ticket_id, asset_id, site_id = _create_ticket(company_id=company_id, suffix="SWAP", service_type="SWAP_BIN")
    _add_proof(company_id=company_id, ticket_id=ticket_id, photo_type="SWAP_PROOF")

    _complete_ticket(company_id=company_id, ticket_id=ticket_id)

    history = client.get(f"/waste-bin/bins/{asset_id}/history", headers=_auth_headers(company_id))
    assert history.status_code == 200, history.text
    rows = history.json()
    assert len(rows) == 2
    movement_types = {row["movement_type"] for row in rows}
    assert movement_types == {"SWAP_OUT", "SWAP_IN"}
    for row in rows:
        assert row["related_ticket_id"] == ticket_id
        if row["movement_type"] == "SWAP_OUT":
            assert row["from_location_type"] == "SITE"
            assert row["from_location_id"] == site_id
        if row["movement_type"] == "SWAP_IN":
            assert row["to_location_type"] == "SITE"
            assert row["to_location_id"] == site_id


def test_landfill_trip_creates_movement():
    company_id = 9803
    ticket_id, asset_id, _site_id = _create_ticket(company_id=company_id, suffix="DUMP", service_type="PICKUP")
    _add_proof(company_id=company_id, ticket_id=ticket_id, photo_type="PICKUP_PROOF")
    _complete_ticket(company_id=company_id, ticket_id=ticket_id)

    create = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/landfill-trips",
        headers=_auth_headers(company_id),
        json={
            "bin_asset_id": asset_id,
            "dump_site_name": "North Landfill",
            "dump_cost_cents": 12000,
            "km_driven": 14,
        },
    )
    assert create.status_code == 200, create.text
    trip_id = create.json()["landfill_trip_id"]

    history = client.get(f"/waste-bin/bins/{asset_id}/history", headers=_auth_headers(company_id))
    assert history.status_code == 200, history.text
    rows = history.json()
    dump_rows = [row for row in rows if row["movement_type"] == "LANDFILL_DUMP"]
    assert len(dump_rows) == 1
    assert dump_rows[0]["related_landfill_trip_id"] == trip_id
    assert dump_rows[0]["to_location_type"] == "LANDFILL"
    assert dump_rows[0]["to_location_id"] == "North Landfill"


def test_bin_history_query_returns_descending_created_at_order():
    company_id = 9804
    site_id = _create_site(company_id=company_id, suffix="ORDER")
    po_id = _seed_job_po(company_id=company_id, suffix="ORDER")
    asset_id = _create_asset(company_id=company_id, suffix="ORDER", site_id=site_id, po_id=po_id)

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        db.add(
            BinMovement(
                company_id=company_id,
                bin_id=asset_id,
                movement_type="DROP",
                from_location_type="YARD",
                from_location_id=None,
                to_location_type="SITE",
                to_location_id=site_id,
                created_at=now - timedelta(hours=2),
            )
        )
        db.add(
            BinMovement(
                company_id=company_id,
                bin_id=asset_id,
                movement_type="LANDFILL_DUMP",
                from_location_type="SITE",
                from_location_id=site_id,
                to_location_type="LANDFILL",
                to_location_id="East Landfill",
                created_at=now - timedelta(hours=1),
            )
        )
        db.add(
            BinMovement(
                company_id=company_id,
                bin_id=asset_id,
                movement_type="RETURN_TO_YARD",
                from_location_type="LANDFILL",
                from_location_id="East Landfill",
                to_location_type="YARD",
                to_location_id=None,
                created_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    history = client.get(f"/waste-bin/bins/{asset_id}/history", headers=_auth_headers(company_id))
    assert history.status_code == 200, history.text
    movement_types = [row["movement_type"] for row in history.json()]
    assert movement_types == ["RETURN_TO_YARD", "LANDFILL_DUMP", "DROP"]


def test_company_scoping_enforced_for_movement_endpoints():
    company_id = 9805
    other_company = 9806

    ticket_id, asset_id, _site_id = _create_ticket(company_id=company_id, suffix="SCOPE", service_type="DROP_BIN")
    _add_proof(company_id=company_id, ticket_id=ticket_id, photo_type="DROP_PROOF")
    _complete_ticket(company_id=company_id, ticket_id=ticket_id)

    history_other = client.get(f"/waste-bin/bins/{asset_id}/history", headers=_auth_headers(other_company))
    assert history_other.status_code == 404, history_other.text

    all_other = client.get("/waste-bin/movements", headers=_auth_headers(other_company))
    assert all_other.status_code == 200, all_other.text
    assert all_other.json() == []

    all_owner = client.get("/waste-bin/movements", headers=_auth_headers(company_id))
    assert all_owner.status_code == 200, all_owner.text
    assert len(all_owner.json()) >= 1


def test_bin_return_to_yard_action_creates_movement():
    company_id = 9807
    site_id = _create_site(company_id=company_id, suffix="RETURN")
    po_id = _seed_job_po(company_id=company_id, suffix="RETURN")
    asset_id = _create_asset(company_id=company_id, suffix="RETURN", site_id=site_id, po_id=po_id)

    ret = client.post(
        f"/waste-bin/assets/{asset_id}/return-to-yard",
        headers=_auth_headers(company_id),
        json={"from_location_type": "SITE", "from_location_id": site_id},
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["status"] == "AVAILABLE"
    assert ret.json()["current_customer_site_id"] is None

    history = client.get(f"/waste-bin/bins/{asset_id}/history", headers=_auth_headers(company_id))
    assert history.status_code == 200, history.text
    rows = history.json()
    assert len(rows) == 1
    assert rows[0]["movement_type"] == "RETURN_TO_YARD"
    assert rows[0]["from_location_type"] == "SITE"
    assert rows[0]["from_location_id"] == site_id
    assert rows[0]["to_location_type"] == "YARD"

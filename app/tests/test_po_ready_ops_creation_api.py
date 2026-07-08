from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.bin_service_request import BinServiceRequest
from app.models.bin_service_ticket import BinServiceTicket
from app.models.customer_site import CustomerSite
from app.models.foundation_work_package import FoundationWorkPackage
from app.models.job import Job
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "test-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_job_scope(company_id: int, scope_name: str, name_suffix: str) -> tuple[int, int]:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"PO Ops Job {name_suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=scope_name)
        db.add(scope)
        db.commit()
        return int(job.id), int(scope.id)
    finally:
        db.close()


def _seed_customer_site(company_id: int, name_suffix: str) -> str:
    db = SessionLocal()
    try:
        site = CustomerSite(
            company_id=company_id,
            customer_name=f"Customer {name_suffix}",
            site_name=f"Site {name_suffix}",
            address_line_1=f"{name_suffix} Main St",
            city="Calgary",
            province="AB",
            postal_code="T2P1J9",
        )
        db.add(site)
        db.commit()
        db.refresh(site)
        return str(site.customer_site_id)
    finally:
        db.close()


def _create_po(*, company_id: int, job_id: int, scope_id: int, po_number: str) -> dict:
    resp = client.post(
        "/job-documents/purchase-orders",
        headers=_auth_headers(company_id),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "po_number": po_number,
            "status": "ISSUED",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _match_po(*, company_id: int, po_id: str, job_id: int, scope_id: int, site_id: str) -> None:
    resp = client.post(
        f"/job-documents/purchase-orders/{po_id}/match",
        headers=_auth_headers(company_id),
        json={
            "matched_job_id": job_id,
            "matched_scope_id": scope_id,
            "matched_customer_site_id": site_id,
        },
    )
    assert resp.status_code == 200, resp.text


def test_ready_for_ops_creates_waste_bin_request_and_ticket():
    company_id = 9801
    job_id, scope_id = _seed_job_scope(company_id=company_id, scope_name="Waste Bin Swap Service", name_suffix="A")
    site_id = _seed_customer_site(company_id=company_id, name_suffix="A")
    po = _create_po(company_id=company_id, job_id=job_id, scope_id=scope_id, po_number="PO-OPS-WASTE-1")

    _match_po(
        company_id=company_id,
        po_id=po["job_purchase_order_id"],
        job_id=job_id,
        scope_id=scope_id,
        site_id=site_id,
    )

    ready = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(company_id),
        json={},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["queue_status"] == "READY_FOR_OPS"

    db = SessionLocal()
    try:
        reqs = (
            db.query(BinServiceRequest)
            .filter(BinServiceRequest.company_id == company_id)
            .filter(BinServiceRequest.job_purchase_order_id == po["job_purchase_order_id"])
            .filter(BinServiceRequest.request_source == "PO_READY_FOR_OPS")
            .all()
        )
        assert len(reqs) == 1
        assert reqs[0].customer_site_id == site_id
        assert str(reqs[0].request_type) == "SWAP"
        assert str(reqs[0].status) == "OPEN"

        tickets = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.job_purchase_order_id == po["job_purchase_order_id"])
            .all()
        )
        assert len(tickets) == 1
        assert str(tickets[0].status) == "OPEN"
        assert str(tickets[0].service_type) == "SWAP"
        assert str(tickets[0].bin_service_request_id) == str(reqs[0].bin_service_request_id)
    finally:
        db.close()


def test_ready_for_ops_creates_foundation_work_package():
    company_id = 9802
    job_id, scope_id = _seed_job_scope(company_id=company_id, scope_name="Foundation Footing", name_suffix="B")
    site_id = _seed_customer_site(company_id=company_id, name_suffix="B")
    po = _create_po(company_id=company_id, job_id=job_id, scope_id=scope_id, po_number="PO-OPS-FOUND-1")

    _match_po(
        company_id=company_id,
        po_id=po["job_purchase_order_id"],
        job_id=job_id,
        scope_id=scope_id,
        site_id=site_id,
    )

    ready = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(company_id),
        json={},
    )
    assert ready.status_code == 200, ready.text

    db = SessionLocal()
    try:
        fwps = (
            db.query(FoundationWorkPackage)
            .filter(FoundationWorkPackage.company_id == company_id)
            .filter(FoundationWorkPackage.job_purchase_order_id == po["job_purchase_order_id"])
            .all()
        )
        assert len(fwps) == 1
        assert int(fwps[0].job_id) == job_id
        assert int(fwps[0].scope_id) == scope_id
        assert str(fwps[0].status) == "READY"

        reqs = (
            db.query(BinServiceRequest)
            .filter(BinServiceRequest.company_id == company_id)
            .filter(BinServiceRequest.job_purchase_order_id == po["job_purchase_order_id"])
            .all()
        )
        assert reqs == []
    finally:
        db.close()


def test_duplicate_ready_transition_does_not_duplicate_ops_records():
    company_id = 9803
    job_id, scope_id = _seed_job_scope(company_id=company_id, scope_name="Waste Bin Drop", name_suffix="C")
    site_id = _seed_customer_site(company_id=company_id, name_suffix="C")
    po = _create_po(company_id=company_id, job_id=job_id, scope_id=scope_id, po_number="PO-OPS-WASTE-2")

    _match_po(
        company_id=company_id,
        po_id=po["job_purchase_order_id"],
        job_id=job_id,
        scope_id=scope_id,
        site_id=site_id,
    )

    ready_1 = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(company_id),
        json={},
    )
    assert ready_1.status_code == 200, ready_1.text

    ready_2 = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(company_id),
        json={},
    )
    assert ready_2.status_code == 200, ready_2.text

    db = SessionLocal()
    try:
        req_count = (
            db.query(BinServiceRequest)
            .filter(BinServiceRequest.company_id == company_id)
            .filter(BinServiceRequest.job_purchase_order_id == po["job_purchase_order_id"])
            .count()
        )
        ticket_count = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.job_purchase_order_id == po["job_purchase_order_id"])
            .count()
        )
        assert req_count == 1
        assert ticket_count == 1
    finally:
        db.close()


def test_ready_for_ops_company_scoping_enforced_for_ops_creation():
    c1 = 9804
    c2 = 9805

    job_id, scope_id = _seed_job_scope(company_id=c1, scope_name="Foundation Prep", name_suffix="D")
    site_id = _seed_customer_site(company_id=c1, name_suffix="D")
    po = _create_po(company_id=c1, job_id=job_id, scope_id=scope_id, po_number="PO-OPS-SCOPE-1")

    _match_po(
        company_id=c1,
        po_id=po["job_purchase_order_id"],
        job_id=job_id,
        scope_id=scope_id,
        site_id=site_id,
    )

    ready_other_company = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(c2),
        json={},
    )
    assert ready_other_company.status_code == 404, ready_other_company.text

    db = SessionLocal()
    try:
        c2_reqs = db.query(BinServiceRequest).filter(BinServiceRequest.company_id == c2).all()
        c2_tickets = db.query(BinServiceTicket).filter(BinServiceTicket.company_id == c2).all()
        c2_fwps = db.query(FoundationWorkPackage).filter(FoundationWorkPackage.company_id == c2).all()
        assert c2_reqs == []
        assert c2_tickets == []
        assert c2_fwps == []
    finally:
        db.close()


def test_invalid_scope_type_fails_safely_without_creating_ops_records():
    company_id = 9806
    job_id, scope_id = _seed_job_scope(company_id=company_id, scope_name="Electrical Rough-In", name_suffix="E")
    site_id = _seed_customer_site(company_id=company_id, name_suffix="E")
    po = _create_po(company_id=company_id, job_id=job_id, scope_id=scope_id, po_number="PO-OPS-INVALID-1")

    _match_po(
        company_id=company_id,
        po_id=po["job_purchase_order_id"],
        job_id=job_id,
        scope_id=scope_id,
        site_id=site_id,
    )

    ready = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(company_id),
        json={},
    )
    assert ready.status_code == 422, ready.text
    assert "Unable to determine operational type" in ready.json()["detail"]

    db = SessionLocal()
    try:
        reqs = (
            db.query(BinServiceRequest)
            .filter(BinServiceRequest.company_id == company_id)
            .filter(BinServiceRequest.job_purchase_order_id == po["job_purchase_order_id"])
            .all()
        )
        tickets = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.job_purchase_order_id == po["job_purchase_order_id"])
            .all()
        )
        fwps = (
            db.query(FoundationWorkPackage)
            .filter(FoundationWorkPackage.company_id == company_id)
            .filter(FoundationWorkPackage.job_purchase_order_id == po["job_purchase_order_id"])
            .all()
        )
        assert reqs == []
        assert tickets == []
        assert fwps == []
    finally:
        db.close()

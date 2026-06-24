from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.invoice import Invoice
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.scope import Scope
from app.services.invoice_service import generate_invoice_for_completed_ticket

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
        job = Job(company_id=company_id, name=f"Waste Bin Invoice Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Waste Bin Invoice Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-WB-INV-{suffix}",
            status="ISSUED",
        )
        db.add(po)
        db.commit()
        return str(po.job_purchase_order_id)
    finally:
        db.close()


def _create_site(company_id: int, customer_name: str, address: str) -> str:
    resp = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": customer_name,
            "site_name": "Main Site",
            "address_line_1": address,
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T8T8T8",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["customer_site_id"])


def _create_ticket(company_id: int, suffix: str, service_type: str) -> str:
    site_id = _create_site(company_id=company_id, customer_name=f"Builder {suffix}", address=f"{suffix} Invoice Way")
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


def _add_required_proof(company_id: int, ticket_id: str, service_type: str) -> None:
    proof_type = {"DROP": "DROP_PROOF", "SWAP": "SWAP_PROOF", "PICKUP": "PICKUP_PROOF"}[service_type]
    photo = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": proof_type,
            "storage_key": f"placeholder://{ticket_id}-{proof_type}",
            "captured_at": "2026-03-06T12:00:00Z",
        },
    )
    assert photo.status_code == 200, photo.text


def test_invoice_created_when_ticket_completed(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_DROP_CENTS", "15000")

    company_id = 9801
    ticket_id = _create_ticket(company_id=company_id, suffix="A", service_type="DROP")
    _add_required_proof(company_id=company_id, ticket_id=ticket_id, service_type="DROP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    invoice = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/invoice",
        headers=_auth_headers(company_id),
    )
    assert invoice.status_code == 200, invoice.text
    row = invoice.json()
    assert row["service_ticket_id"] == ticket_id
    assert row["status"] == "DRAFT"
    assert len(row["lines"]) == 1


def test_invoice_includes_po_number_and_site(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_SWAP_CENTS", "17000")

    company_id = 9802
    ticket_id = _create_ticket(company_id=company_id, suffix="B", service_type="SWAP")
    _add_required_proof(company_id=company_id, ticket_id=ticket_id, service_type="SWAP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    invoice = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/invoice",
        headers=_auth_headers(company_id),
    )
    assert invoice.status_code == 200, invoice.text
    row = invoice.json()
    assert row["po_number"] == "PO-WB-INV-B"
    assert "B Invoice Way" in row["billing_address"]
    assert row["customer_name"] == "Builder B"


def test_duplicate_prevention_works_for_service_ticket_invoice(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_PICKUP_CENTS", "9000")

    company_id = 9803
    ticket_id = _create_ticket(company_id=company_id, suffix="C", service_type="PICKUP")
    _add_required_proof(company_id=company_id, ticket_id=ticket_id, service_type="PICKUP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    db = SessionLocal()
    try:
        inv1 = generate_invoice_for_completed_ticket(company_id=company_id, service_ticket_id=ticket_id, db=db)
        inv2 = generate_invoice_for_completed_ticket(company_id=company_id, service_ticket_id=ticket_id, db=db)
        db.commit()
        assert str(inv1.invoice_id) == str(inv2.invoice_id)

        count = (
            db.query(Invoice)
            .filter(Invoice.company_id == company_id)
            .filter(Invoice.service_ticket_id == ticket_id)
            .count()
        )
        assert count == 1
    finally:
        db.close()


def test_invoice_totals_computed_correctly(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_DROP_CENTS", "20000")

    company_id = 9804
    ticket_id = _create_ticket(company_id=company_id, suffix="D", service_type="DROP")
    _add_required_proof(company_id=company_id, ticket_id=ticket_id, service_type="DROP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    invoice = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/invoice",
        headers=_auth_headers(company_id),
    )
    assert invoice.status_code == 200, invoice.text
    row = invoice.json()

    assert row["subtotal_cents"] == 20000
    assert row["tax_cents"] == 0
    assert row["total_cents"] == 20000
    assert row["lines"][0]["unit_price_cents"] == 20000
    assert row["lines"][0]["line_total_cents"] == 20000


def test_company_scoping_enforced_for_invoice_endpoints(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_SWAP_CENTS", "19000")

    company_id = 9805
    other_company = 9806
    ticket_id = _create_ticket(company_id=company_id, suffix="E", service_type="SWAP")
    _add_required_proof(company_id=company_id, ticket_id=ticket_id, service_type="SWAP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    own_invoice = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/invoice",
        headers=_auth_headers(company_id),
    )
    assert own_invoice.status_code == 200, own_invoice.text
    invoice_id = own_invoice.json()["invoice_id"]

    list_other = client.get("/invoices", headers=_auth_headers(other_company))
    assert list_other.status_code == 200, list_other.text
    assert list_other.json() == []

    get_other = client.get(f"/invoices/{invoice_id}", headers=_auth_headers(other_company))
    assert get_other.status_code == 404, get_other.text

    ticket_invoice_other = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/invoice",
        headers=_auth_headers(other_company),
    )
    assert ticket_invoice_other.status_code == 404, ticket_invoice_other.text

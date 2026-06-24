from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.scope import Scope

client = TestClient(app)


TICKET_COMPLETED_EVENT = "WASTE_BIN_TICKET_COMPLETED_CONFIRMATION_READY"
INVOICE_SEND_EVENT = "INVOICE_SEND_READY"


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
        job = Job(company_id=company_id, name=f"Invoice Workflow Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Invoice Workflow Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-WB-WF-{suffix}",
            status="ISSUED",
        )
        db.add(po)
        db.commit()
        return str(po.job_purchase_order_id)
    finally:
        db.close()


def _create_ready_ticket(company_id: int, suffix: str, service_type: str = "DROP") -> tuple[str, str]:
    site = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": f"Builder {suffix}",
            "site_name": "Main",
            "address_line_1": f"{suffix} Workflow Ave",
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T9T9T9",
        },
    )
    assert site.status_code == 200, site.text
    site_id = site.json()["customer_site_id"]

    po_id = _seed_job_po(company_id=company_id, suffix=suffix)

    req = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": service_type,
            "request_notes": "workflow",
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
    ticket_id = ticket.json()["bin_service_ticket_id"]

    proof_map = {"DROP": "DROP_PROOF", "SWAP": "SWAP_PROOF", "PICKUP": "PICKUP_PROOF"}
    proof = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": proof_map[service_type],
            "storage_key": f"placeholder://wf-{suffix}",
            "captured_at": "2026-03-06T13:00:00Z",
        },
    )
    assert proof.status_code == 200, proof.text

    return str(ticket_id), str(po_id)


def _outbox_for_event(company_id: int, event_type: str) -> list[EventOutbox]:
    db = SessionLocal()
    try:
        return (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.event_type == event_type)
            .order_by(EventOutbox.id.asc())
            .all()
        )
    finally:
        db.close()


def test_service_ticket_completion_enqueues_confirmation_event(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_DROP_CENTS", "10000")

    company_id = 9901
    ticket_id, _po_id = _create_ready_ticket(company_id=company_id, suffix="A", service_type="DROP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    rows = _outbox_for_event(company_id=company_id, event_type=TICKET_COMPLETED_EVENT)
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["company_id"] == company_id
    assert payload["bin_service_ticket_id"] == ticket_id
    assert payload["service_type"] == "DROP"
    assert payload["customer_site_id"] == complete.json()["customer_site_id"]
    assert payload["completed_at"] is not None
    assert payload["po_number"] == "PO-WB-WF-A"
    assert "Workflow Ave" in payload["address_summary"]


def test_invoice_issue_from_draft_and_send_from_issued_succeeds(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_SWAP_CENTS", "12000")

    company_id = 9902
    ticket_id, _po_id = _create_ready_ticket(company_id=company_id, suffix="B", service_type="SWAP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    invoice = client.get(f"/waste-bin/service-tickets/{ticket_id}/invoice", headers=_auth_headers(company_id))
    assert invoice.status_code == 200, invoice.text
    invoice_id = invoice.json()["invoice_id"]
    assert invoice.json()["status"] == "DRAFT"

    issue = client.post(f"/invoices/{invoice_id}/issue", headers=_auth_headers(company_id))
    assert issue.status_code == 200, issue.text
    assert issue.json()["status"] == "ISSUED"

    send = client.post(f"/invoices/{invoice_id}/send", headers=_auth_headers(company_id))
    assert send.status_code == 200, send.text
    assert send.json()["status"] == "SENT"

    send_outbox = _outbox_for_event(company_id=company_id, event_type=INVOICE_SEND_EVENT)
    assert len(send_outbox) == 1
    payload = send_outbox[0].payload
    assert payload["invoice_id"] == invoice_id
    assert payload["company_id"] == company_id
    assert payload["po_number"] == "PO-WB-WF-B"
    assert payload["total_cents"] == 12000
    assert payload["service_ticket_id"] == ticket_id


def test_sending_already_sent_invoice_fails_with_409_and_no_duplicate_send_event(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_PICKUP_CENTS", "9000")

    company_id = 9903
    ticket_id, _po_id = _create_ready_ticket(company_id=company_id, suffix="C", service_type="PICKUP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    invoice = client.get(f"/waste-bin/service-tickets/{ticket_id}/invoice", headers=_auth_headers(company_id))
    invoice_id = invoice.json()["invoice_id"]

    issue = client.post(f"/invoices/{invoice_id}/issue", headers=_auth_headers(company_id))
    assert issue.status_code == 200, issue.text

    send_1 = client.post(f"/invoices/{invoice_id}/send", headers=_auth_headers(company_id))
    assert send_1.status_code == 200, send_1.text

    send_2 = client.post(f"/invoices/{invoice_id}/send", headers=_auth_headers(company_id))
    assert send_2.status_code == 409, send_2.text

    rows = _outbox_for_event(company_id=company_id, event_type=INVOICE_SEND_EVENT)
    assert len(rows) == 1


def test_invalid_transition_fails_with_409(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_DROP_CENTS", "15000")

    company_id = 9904
    ticket_id, _po_id = _create_ready_ticket(company_id=company_id, suffix="D", service_type="DROP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    invoice = client.get(f"/waste-bin/service-tickets/{ticket_id}/invoice", headers=_auth_headers(company_id))
    invoice_id = invoice.json()["invoice_id"]

    send_from_draft = client.post(f"/invoices/{invoice_id}/send", headers=_auth_headers(company_id))
    assert send_from_draft.status_code == 409, send_from_draft.text

    issue = client.post(f"/invoices/{invoice_id}/issue", headers=_auth_headers(company_id))
    assert issue.status_code == 200, issue.text

    send = client.post(f"/invoices/{invoice_id}/send", headers=_auth_headers(company_id))
    assert send.status_code == 200, send.text

    issue_after_sent = client.post(f"/invoices/{invoice_id}/issue", headers=_auth_headers(company_id))
    assert issue_after_sent.status_code == 409, issue_after_sent.text


def test_company_scoping_enforced_for_issue_and_send(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_DROP_CENTS", "18000")

    company_id = 9905
    other_company = 9906
    ticket_id, _po_id = _create_ready_ticket(company_id=company_id, suffix="E", service_type="DROP")

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    invoice = client.get(f"/waste-bin/service-tickets/{ticket_id}/invoice", headers=_auth_headers(company_id))
    invoice_id = invoice.json()["invoice_id"]

    issue_other = client.post(f"/invoices/{invoice_id}/issue", headers=_auth_headers(other_company))
    assert issue_other.status_code == 404, issue_other.text

    send_other = client.post(f"/invoices/{invoice_id}/send", headers=_auth_headers(other_company))
    assert send_other.status_code == 404, send_other.text


def test_duplicate_confirmation_event_not_created_on_failed_second_completion(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_SWAP_CENTS", "11000")

    company_id = 9907
    ticket_id, _po_id = _create_ready_ticket(company_id=company_id, suffix="F", service_type="SWAP")

    first = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "again"},
    )
    assert second.status_code == 409, second.text

    rows = _outbox_for_event(company_id=company_id, event_type=TICKET_COMPLETED_EVENT)
    assert len(rows) == 1

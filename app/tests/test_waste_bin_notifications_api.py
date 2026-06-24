from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.scope import Scope

client = TestClient(app)


ACK_EVENT = "BIN_SERVICE_REQUEST_EMAIL_ACK_READY"
COMPLETION_EVENT = "WASTE_BIN_TICKET_COMPLETED_CONFIRMATION_READY"


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _seed_po(company_id: int, suffix: str) -> str:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"Notif Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Notif Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-NOTIF-{suffix}",
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
            "customer_name": f"Notif Builder {suffix}",
            "site_name": "Main Yard",
            "address_line_1": f"{suffix} Notification Ave",
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T4T4T4",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["customer_site_id"])


def _create_request(company_id: int, suffix: str, request_type: str = "DROP") -> tuple[str, str, str]:
    site_id = _create_site(company_id=company_id, suffix=suffix)
    po_id = _seed_po(company_id=company_id, suffix=suffix)

    req = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": request_type,
            "request_notes": "notif request",
        },
    )
    assert req.status_code == 200, req.text
    return str(req.json()["bin_service_request_id"]), str(site_id), str(po_id)


def _create_ticket(company_id: int, suffix: str, service_type: str = "DROP") -> tuple[str, str, str]:
    req_id, site_id, po_id = _create_request(company_id=company_id, suffix=suffix, request_type="DROP")

    ticket = client.post(
        "/waste-bin/service-tickets",
        headers=_auth_headers(company_id),
        json={
            "bin_service_request_id": req_id,
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "service_type": service_type,
            "status": "OPEN",
        },
    )
    assert ticket.status_code == 200, ticket.text
    return str(ticket.json()["bin_service_ticket_id"]), str(site_id), str(po_id)


def _add_drop_proof(company_id: int, ticket_id: str):
    proof = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": "DROP_PROOF",
            "storage_key": f"placeholder://proof-{ticket_id}",
            "captured_at": "2026-03-06T16:00:00Z",
        },
    )
    assert proof.status_code == 200, proof.text


def _outbox_rows(company_id: int, event_type: str) -> list[EventOutbox]:
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


def test_ack_preview_content():
    company_id = 9971
    request_id, _site_id, _po_id = _create_request(company_id=company_id, suffix="A")

    preview = client.get(
        f"/waste-bin/service-requests/{request_id}/ack-preview",
        headers=_auth_headers(company_id),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["message_type"] == "REQUEST_ACKNOWLEDGEMENT"
    assert "Acknowledged" in body["subject"]
    assert "Request type: DROP" in body["body"]
    assert "Notification Ave" in body["body"]
    assert "PO-NOTIF-A" in body["body"]


def test_completion_preview_content():
    company_id = 9972
    ticket_id, site_id, po_id = _create_ticket(company_id=company_id, suffix="B", service_type="DROP")

    asset = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(company_id),
        json={
            "bin_number": "NOTIF-BIN-B",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
            "current_customer_site_id": site_id,
            "current_job_purchase_order_id": po_id,
        },
    )
    assert asset.status_code == 200, asset.text
    bin_asset_id = str(asset.json()["bin_asset_id"])

    assignment = client.patch(
        f"/waste-bin/service-tickets/{ticket_id}/assignment",
        headers=_auth_headers(company_id),
        json={
            "assigned_bin_asset_id": bin_asset_id,
            "assigned_vehicle_label": "Truck-B",
        },
    )
    assert assignment.status_code == 200, assignment.text

    _add_drop_proof(company_id, ticket_id)

    complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete.status_code == 200, complete.text

    preview = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/completion-preview",
        headers=_auth_headers(company_id),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()["body"]
    assert "Service type: DROP" in body
    assert "Assigned bin: NOTIF-BIN-B" in body
    assert "Assigned vehicle: Truck-B" in body
    assert "Completed at:" in body


def test_work_order_content_includes_what_where_when():
    company_id = 9973
    ticket_id, site_id, po_id = _create_ticket(company_id=company_id, suffix="C", service_type="DROP")

    asset = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(company_id),
        json={
            "bin_number": "NOTIF-BIN-C",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
            "current_customer_site_id": site_id,
            "current_job_purchase_order_id": po_id,
        },
    )
    assert asset.status_code == 200, asset.text
    bin_asset_id = str(asset.json()["bin_asset_id"])

    schedule = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/schedule",
        headers=_auth_headers(company_id),
        json={
            "scheduled_date": date.today().isoformat(),
            "scheduled_time_window": "09:00-11:00",
            "priority": "NORMAL",
        },
    )
    assert schedule.status_code == 200, schedule.text

    assignment = client.patch(
        f"/waste-bin/service-tickets/{ticket_id}/assignment",
        headers=_auth_headers(company_id),
        json={
            "assigned_bin_asset_id": bin_asset_id,
            "assigned_vehicle_label": "Truck-C",
        },
    )
    assert assignment.status_code == 200, assignment.text

    preview = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/work-order",
        headers=_auth_headers(company_id),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()["body"]
    assert "Service type: DROP" in body
    assert "Notification Ave" in body
    assert "Scheduled date:" in body
    assert "Scheduled window: 09:00-11:00" in body
    assert "Assigned bin: NOTIF-BIN-C" in body
    assert "Assigned vehicle: Truck-C" in body


def test_duplicate_send_ready_behavior_prevented_for_ack_and_completion(monkeypatch):
    monkeypatch.setenv("WASTE_BIN_PRICE_DROP_CENTS", "10000")

    company_id = 9974

    event = client.post(
        "/job-documents/email-ingestion-events",
        headers=_auth_headers(company_id),
        json={
            "source_message_id": "msg-ack-dupe",
            "sender_email": "ops@example.com",
            "subject": "Need a drop at 100 Duplicate St",
            "parse_status": "PARSED",
        },
    )
    assert event.status_code == 200, event.text
    event_id = event.json()["email_ingestion_event_id"]

    c1 = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(company_id),
        json={"email_ingestion_event_id": event_id, "parsed_text": "drop bin"},
    )
    assert c1.status_code == 200, c1.text

    c2 = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(company_id),
        json={"email_ingestion_event_id": event_id, "parsed_text": "drop bin"},
    )
    assert c2.status_code == 200, c2.text

    ack_rows = _outbox_rows(company_id=company_id, event_type=ACK_EVENT)
    assert len(ack_rows) == 1

    ticket_id, _site_id, _po_id = _create_ticket(company_id=company_id, suffix="D", service_type="DROP")
    _add_drop_proof(company_id, ticket_id)

    first_complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert first_complete.status_code == 200, first_complete.text

    second_complete = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "again"},
    )
    assert second_complete.status_code == 409, second_complete.text

    completion_rows = _outbox_rows(company_id=company_id, event_type=COMPLETION_EVENT)
    assert len(completion_rows) == 1


def test_company_scoping_enforced_for_preview_endpoints():
    company_id = 9975
    other_company = 9976
    request_id, _site_id, _po_id = _create_request(company_id=company_id, suffix="E")
    ticket_id, _site_id2, _po_id2 = _create_ticket(company_id=company_id, suffix="E2", service_type="DROP")

    ack_other = client.get(
        f"/waste-bin/service-requests/{request_id}/ack-preview",
        headers=_auth_headers(other_company),
    )
    assert ack_other.status_code == 404, ack_other.text

    completion_other = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/completion-preview",
        headers=_auth_headers(other_company),
    )
    assert completion_other.status_code == 404, completion_other.text

    work_order_other = client.get(
        f"/waste-bin/service-tickets/{ticket_id}/work-order",
        headers=_auth_headers(other_company),
    )
    assert work_order_other.status_code == 404, work_order_other.text

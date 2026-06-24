from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.scope import Scope
from app.services.bin_email_intake_service import BIN_SERVICE_REQUEST_EMAIL_ACK_READY

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_job_po(company_id: int, suffix: str, po_number: str) -> str:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"Waste Bin Email Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Waste Bin Email Scope {suffix}")
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
        return str(po.job_purchase_order_id)
    finally:
        db.close()


def _create_email_event(company_id: int, subject: str, parsed_po_number: str | None = None) -> str:
    body = {
        "source_message_id": f"msg-{company_id}-{subject.replace(' ', '-').lower()}",
        "sender_email": "ops@example.com",
        "subject": subject,
        "parse_status": "PARSED",
    }
    if parsed_po_number is not None:
        body["parsed_po_number"] = parsed_po_number

    resp = client.post("/job-documents/email-ingestion-events", headers=_auth_headers(company_id), json=body)
    assert resp.status_code == 200, resp.text
    return str(resp.json()["email_ingestion_event_id"])


def _create_site(company_id: int, name: str, address: str) -> str:
    resp = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": name,
            "site_name": f"{name} Main Site",
            "address_line_1": address,
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T6T6T6",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["customer_site_id"])


def _outbox_rows_for_request(company_id: int, request_id: str) -> list[EventOutbox]:
    db = SessionLocal()
    try:
        rows = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.event_type == BIN_SERVICE_REQUEST_EMAIL_ACK_READY)
            .all()
        )
        return [row for row in rows if str(row.payload.get("bin_service_request_id")) == str(request_id)]
    finally:
        db.close()


def test_email_subject_and_body_create_drop_request():
    company_id = 9501
    event_id = _create_email_event(company_id, "Need a bin drop at 100 Main St")

    created = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Please drop a new 20yd bin tomorrow",
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["request_type"] == "DROP"
    assert row["status"] == "OPEN"
    assert row["source_email_ingestion_event_id"] == event_id


def test_email_subject_and_body_create_swap_request():
    company_id = 9502
    event_id = _create_email_event(company_id, "SWAP required at site")

    created = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Please swap bin at the same location",
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["request_type"] == "SWAP"
    assert row["status"] == "OPEN"


def test_request_links_to_po_when_parsed_po_number_matches():
    company_id = 9503
    po_number = "PO-WB-9503"
    po_id = _seed_job_po(company_id=company_id, suffix="PO", po_number=po_number)
    event_id = _create_email_event(company_id, "Pickup request for PO", parsed_po_number=po_number)

    created = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Please pickup this full container",
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["request_type"] == "PICKUP"
    assert row["job_purchase_order_id"] == po_id


def test_request_links_to_customer_site_when_deterministic_match_is_possible():
    company_id = 9504
    site_id = _create_site(company_id=company_id, name="Big Build", address="100 Deterministic Ave")
    event_id = _create_email_event(company_id, "Need drop at 100 Deterministic Ave")

    created = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Drop please at 100 Deterministic Ave Edmonton AB",
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["customer_site_id"] == site_id


def test_unmatched_email_still_creates_request_with_notes_and_no_bad_linkage():
    company_id = 9505
    event_id = _create_email_event(company_id, "Can you help with site logistics?")

    created = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "No PO and no exact address in this message",
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["customer_site_id"] is None
    assert row["job_purchase_order_id"] is None
    assert "parsed_po_number=none" in str(row["request_notes"])


def test_exactly_one_outbox_event_is_enqueued_for_email_request_creation():
    company_id = 9506
    event_id = _create_email_event(company_id, "DROP for 700 Outbox Rd")

    created = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "drop bin at 700 Outbox Rd",
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()

    outbox_rows = _outbox_rows_for_request(company_id=company_id, request_id=row["bin_service_request_id"])
    assert len(outbox_rows) == 1

    payload = outbox_rows[0].payload
    assert payload["company_id"] == company_id
    assert payload["bin_service_request_id"] == row["bin_service_request_id"]
    assert payload["request_type"] == row["request_type"]
    assert payload["customer_site_id"] == row["customer_site_id"]
    assert payload["job_purchase_order_id"] == row["job_purchase_order_id"]
    assert payload["source_email_ingestion_event_id"] == event_id


def test_company_scoping_enforced_for_email_event_lookup_and_list_filters():
    company_id = 9507
    other_company = 9508

    site_id = _create_site(company_id=company_id, name="Filter Test", address="555 Filter Ln")
    event_id = _create_email_event(company_id, "Swap request 555 Filter Ln")

    created = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "swap required at 555 Filter Ln",
        },
    )
    assert created.status_code == 200, created.text
    req = created.json()
    assert req["customer_site_id"] == site_id

    cross_company = client.post(
        "/waste-bin/service-requests/from-email",
        headers=_auth_headers(other_company),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "swap required at 555 Filter Ln",
        },
    )
    assert cross_company.status_code == 404, cross_company.text

    filtered = client.get(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        params={
            "source_email_ingestion_event_id": event_id,
            "request_type": "SWAP",
            "status": "OPEN",
        },
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["bin_service_request_id"] == req["bin_service_request_id"]

    other_list = client.get(
        "/waste-bin/service-requests",
        headers=_auth_headers(other_company),
        params={"source_email_ingestion_event_id": event_id},
    )
    assert other_list.status_code == 200, other_list.text
    assert other_list.json() == []

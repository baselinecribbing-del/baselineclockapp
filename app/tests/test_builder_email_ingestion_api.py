from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.email_ingestion_event import EmailIngestionEvent
from app.models.event_outbox import EventOutbox
from app.models.job_document import JobDocument
from app.models.job_start_intake import JobStartIntake
from app.services.job_intake_service import NEW_START_RECEIVED_NOTIFICATION_READY

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "builder-email-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _payload(company_id: int) -> dict:
    return {
        "company_id": company_id,
        "source": "builder_email",
        "from_email": "starts@jayman.com",
        "subject": "New Start - Lot 12 Block 5",
        "received_at": datetime(2026, 3, 10, 15, 30, tzinfo=timezone.utc).isoformat(),
        "body_text": (
            "Builder: Jayman Homes\n"
            "Project Address: 100 Automation Way, Edmonton AB\n"
            "Lot 12 Block 5\n"
            "Stake Date: 2026-04-15"
        ),
        "attachments": [
            {
                "filename": "blueprint.pdf",
                "storage_key": "builder-email/blueprint.pdf",
                "content_type": "application/pdf",
            },
            {
                "filename": "grade slip.pdf",
                "storage_key": "builder-email/grade-slip.pdf",
                "content_type": "application/pdf",
            },
            {
                "filename": "site plan.pdf",
                "storage_key": "builder-email/site-plan.pdf",
                "content_type": "application/pdf",
            },
        ],
    }


def test_builder_email_creates_intake_record():
    company_id = 54001

    resp = client.post("/email-ingestion-events", headers=_auth_headers(company_id), json=_payload(company_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["company_id"] == company_id
    assert body["builder_name"] == "Jayman Homes"
    assert body["project_address"] == "100 Automation Way, Edmonton AB"
    assert body["lot_number"] == "12"
    assert body["block_number"] == "5"
    assert body["stake_date"] == "2026-04-15"
    assert body["queue_trigger_date"] == "2026-04-15"
    assert body["intake_status"] == "QUEUED"
    assert body["event_emitted"] is True
    assert body["idempotent_replay"] is False
    assert len(body["attachments"]) == 3

    db = SessionLocal()
    try:
        event = (
            db.query(EmailIngestionEvent)
            .filter(EmailIngestionEvent.company_id == company_id)
            .filter(EmailIngestionEvent.email_ingestion_event_id == body["email_ingestion_event_id"])
            .one()
        )
        assert event.parse_status == "PARSED"

        intake = (
            db.query(JobStartIntake)
            .filter(JobStartIntake.company_id == company_id)
            .filter(JobStartIntake.job_start_intake_id == body["job_start_intake_id"])
            .one()
        )
        assert intake.project_address == "100 Automation Way, Edmonton AB"
    finally:
        db.close()


def test_builder_email_links_attachments_correctly():
    company_id = 54002

    resp = client.post("/email-ingestion-events", headers=_auth_headers(company_id), json=_payload(company_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    db = SessionLocal()
    try:
        docs = (
            db.query(JobDocument)
            .filter(JobDocument.company_id == company_id)
            .filter(JobDocument.email_ingestion_event_id == body["email_ingestion_event_id"])
            .order_by(JobDocument.file_name.asc())
            .all()
        )
        assert [doc.job_start_intake_id for doc in docs] == [body["job_start_intake_id"]] * 3
        assert [doc.file_name for doc in docs] == ["blueprint.pdf", "grade slip.pdf", "site plan.pdf"]
    finally:
        db.close()


def test_builder_email_blueprint_classification_works():
    company_id = 54003

    resp = client.post("/email-ingestion-events", headers=_auth_headers(company_id), json=_payload(company_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    attachment_types = {row["filename"]: row["document_type"] for row in body["attachments"]}
    assert attachment_types["blueprint.pdf"] == "BLUEPRINT"
    assert attachment_types["grade slip.pdf"] == "GRADE_SLIP"
    assert attachment_types["site plan.pdf"] == "SITE_PLAN"


def test_duplicate_email_events_do_not_create_duplicate_intake_rows():
    company_id = 54004
    payload = _payload(company_id)

    first = client.post("/email-ingestion-events", headers=_auth_headers(company_id), json=payload)
    assert first.status_code == 200, first.text
    second = client.post("/email-ingestion-events", headers=_auth_headers(company_id), json=payload)
    assert second.status_code == 200, second.text

    first_body = first.json()
    second_body = second.json()
    assert second_body["idempotent_replay"] is True
    assert second_body["email_ingestion_event_id"] == first_body["email_ingestion_event_id"]
    assert second_body["job_start_intake_id"] == first_body["job_start_intake_id"]
    assert second_body["event_hash"] == first_body["event_hash"]

    db = SessionLocal()
    try:
        events = db.query(EmailIngestionEvent).filter(EmailIngestionEvent.company_id == company_id).all()
        intakes = db.query(JobStartIntake).filter(JobStartIntake.company_id == company_id).all()
        outbox_rows = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.event_type == NEW_START_RECEIVED_NOTIFICATION_READY)
            .all()
        )
        assert len(events) == 1
        assert len(intakes) == 1
        assert len(outbox_rows) == 1
    finally:
        db.close()


def test_builder_email_ingestion_preserves_company_isolation():
    owner_company_id = 54005
    other_company_id = 54006

    created = client.post(
        "/email-ingestion-events",
        headers=_auth_headers(owner_company_id),
        json=_payload(owner_company_id),
    )
    assert created.status_code == 200, created.text

    mismatch = client.post(
        "/email-ingestion-events",
        headers=_auth_headers(other_company_id),
        json=_payload(owner_company_id),
    )
    assert mismatch.status_code == 403, mismatch.text

    db = SessionLocal()
    try:
        other_company_events = (
            db.query(EmailIngestionEvent)
            .filter(EmailIngestionEvent.company_id == other_company_id)
            .all()
        )
        assert other_company_events == []
    finally:
        db.close()

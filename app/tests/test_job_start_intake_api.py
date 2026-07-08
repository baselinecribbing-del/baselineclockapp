from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_document import JobDocument
from app.services.job_intake_service import NEW_START_RECEIVED_NOTIFICATION_READY

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _create_email_event(
    company_id: int,
    *,
    message_suffix: str,
    sender_email: str = "starts@jayman.com",
    subject: str = "Jayman Homes new start",
    raw_metadata: dict | None = None,
) -> str:
    resp = client.post(
        "/job-documents/email-ingestion-events",
        headers=_auth_headers(company_id),
        json={
            "source_message_id": f"new-start-{company_id}-{message_suffix}",
            "sender_email": sender_email,
            "subject": subject,
            "parse_status": "RECEIVED",
            "raw_metadata": raw_metadata,
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["email_ingestion_event_id"])


def test_valid_new_start_email_creates_queued_intake_and_notification():
    company_id = 9811
    event_id = _create_email_event(
        company_id,
        message_suffix="queued",
        raw_metadata={"builder_name": "Jayman Homes"},
    )

    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": (
                "Builder: Jayman Homes\n"
                "Project Address: 100 Start Lane, Edmonton AB\n"
                "Lot 12 Block 4\n"
                "Stake Date: 2026-04-15"
            ),
            "attachments": [
                {"file_name": "blueprints.pdf", "parsed_text": "foundation blueprint package"},
                {"file_name": "grade slip.pdf", "parsed_text": "grade slip attached"},
                {"file_name": "site plan.pdf", "parsed_text": "site plan attached"},
                {"file_name": "stake date.txt", "parsed_text": "stake date 2026-04-15"},
            ],
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["intake_status"] == "QUEUED"
    assert row["builder_name"] == "Jayman Homes"
    assert row["project_address"] == "100 Start Lane, Edmonton AB"
    assert row["lot_number"] == "12"
    assert row["block_number"] == "4"
    assert row["stake_date"] == "2026-04-15"
    assert row["queue_trigger_date"] == "2026-04-15"
    assert row["has_blueprint"] is True
    assert row["has_grade_slip"] is True
    assert row["has_site_plan"] is True
    assert row["has_stake_date_document"] is True
    assert row["attachments_received"] == {
        "has_blueprint": True,
        "has_grade_slip": True,
        "has_site_plan": True,
        "has_stake_date_document": True,
    }

    db = SessionLocal()
    try:
        docs = (
            db.query(JobDocument)
            .filter(JobDocument.company_id == company_id)
            .filter(JobDocument.email_ingestion_event_id == event_id)
            .order_by(JobDocument.file_name.asc())
            .all()
        )
        assert [doc.document_type for doc in docs] == ["BLUEPRINT", "GRADE_SLIP", "SITE_PLAN", "STAKE_DATE"]

        outbox_rows = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.event_type == NEW_START_RECEIVED_NOTIFICATION_READY)
            .all()
        )
        assert len(outbox_rows) == 1
        payload = outbox_rows[0].payload
        assert payload["email_ingestion_event_id"] == event_id
        assert payload["job_start_intake_id"] == row["job_start_intake_id"]
        assert payload["stake_date"] == "2026-04-15"
        assert payload["queue_trigger_date"] == "2026-04-15"
    finally:
        db.close()


def test_missing_stake_date_is_flagged_and_not_notified():
    company_id = 9812
    event_id = _create_email_event(company_id, message_suffix="flagged")

    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Project Address: 200 Missing Stake Rd\nLot 9 Block 2",
            "attachments": [
                {"file_name": "blueprints.pdf", "parsed_text": "blueprint"},
                {"file_name": "site plan.pdf", "parsed_text": "site plan"},
            ],
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["intake_status"] == "FLAGGED"
    assert row["stake_date"] is None
    assert row["queue_trigger_date"] is None
    assert "Missing stake date" in str(row["parse_notes"])

    db = SessionLocal()
    try:
        outbox_rows = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.event_type == NEW_START_RECEIVED_NOTIFICATION_READY)
            .all()
        )
        assert outbox_rows == []
    finally:
        db.close()


def test_duplicate_new_start_is_marked_duplicate():
    company_id = 9813
    first_event_id = _create_email_event(
        company_id,
        message_suffix="first",
        raw_metadata={"builder_name": "Jayman Homes"},
    )
    second_event_id = _create_email_event(
        company_id,
        message_suffix="second",
        raw_metadata={"builder_name": "Jayman Homes"},
    )

    first = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": first_event_id,
            "parsed_text": "Project Address: 300 Duplicate Ave\nStake Date: 2026-05-01",
            "attachments": [{"file_name": "stake date.txt", "parsed_text": "stake date 2026-05-01"}],
        },
    )
    assert first.status_code == 200, first.text
    first_row = first.json()
    assert first_row["intake_status"] == "QUEUED"

    second = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": second_event_id,
            "parsed_text": "Project Address: 300 Duplicate Ave\nStake Date: 2026-05-01",
            "attachments": [{"file_name": "blueprints.pdf", "parsed_text": "blueprint"}],
        },
    )
    assert second.status_code == 200, second.text
    second_row = second.json()
    assert second_row["intake_status"] == "DUPLICATE"
    assert second_row["duplicate_of_job_start_intake_id"] == first_row["job_start_intake_id"]

    listing = client.get(
        "/job-documents/job-start-intakes",
        headers=_auth_headers(company_id),
        params={"intake_status": "DUPLICATE"},
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["job_start_intake_id"] == second_row["job_start_intake_id"]
    assert rows[0]["queue_trigger_date"] == "2026-05-01"


def test_job_start_intake_list_is_company_scoped():
    c1 = 9814
    c2 = 9815

    event_id = _create_email_event(
        c1,
        message_suffix="scope",
        raw_metadata={"builder_name": "Jayman Homes"},
    )

    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(c1),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Project Address: 400 Scope Way\nStake Date: 2026-06-01",
            "attachments": [{"file_name": "site plan.pdf", "parsed_text": "site plan"}],
        },
    )
    assert created.status_code == 200, created.text

    own = client.get("/job-documents/job-start-intakes", headers=_auth_headers(c1))
    assert own.status_code == 200, own.text
    assert len(own.json()) == 1

    other = client.get("/job-documents/job-start-intakes", headers=_auth_headers(c2))
    assert other.status_code == 200, other.text
    assert other.json() == []


def test_queued_intake_can_be_promoted_into_job_and_linked():
    company_id = 9816
    event_id = _create_email_event(
        company_id,
        message_suffix="promote",
        raw_metadata={"builder_name": "Sterling Homes"},
    )

    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Project Address: 500 Promote Blvd\nStake Date: 2026-06-15",
            "attachments": [
                {"file_name": "blueprints.pdf", "parsed_text": "blueprint package", "storage_key": "s3://docs/blueprint.pdf"},
                {"file_name": "grade slip.pdf", "parsed_text": "grade slip", "storage_key": "s3://docs/grade-slip.pdf"},
                {"file_name": "site plan.pdf", "parsed_text": "site plan", "storage_key": "s3://docs/site-plan.pdf"},
                {"file_name": "stake date.txt", "parsed_text": "stake date 2026-06-15", "storage_key": "s3://docs/stake.txt"},
            ],
        },
    )
    assert created.status_code == 200, created.text
    intake_id = created.json()["job_start_intake_id"]

    promoted = client.post(
        f"/job-documents/job-start-intakes/{intake_id}/promote",
        headers=_auth_headers(company_id),
    )
    assert promoted.status_code == 200, promoted.text
    body = promoted.json()
    assert body["intake_id"] == intake_id
    assert body["promotion_status"] == "PROMOTED"
    assert body["queue_trigger_date"] == "2026-06-15"
    assert body["builder_name"] == "Sterling Homes"
    assert body["project_address"] == "500 Promote Blvd"
    assert body["job_id"] is not None
    assert body["promoted_at"] is not None

    intake_docs = client.get(
        f"/job-documents/job-start-intakes/{intake_id}/documents",
        headers=_auth_headers(company_id),
    )
    assert intake_docs.status_code == 200, intake_docs.text
    intake_doc_rows = intake_docs.json()
    assert [row["document_type"] for row in intake_doc_rows] == ["BLUEPRINT", "GRADE_SLIP", "SITE_PLAN", "STAKE_DATE"]
    assert {row["job_start_intake_id"] for row in intake_doc_rows} == {intake_id}
    promoted_doc_job_ids = {
        row["document_type"]: row["job_id"]
        for row in intake_doc_rows
        if row["document_type"] in {"BLUEPRINT", "GRADE_SLIP", "SITE_PLAN"}
    }
    assert promoted_doc_job_ids == {
        "BLUEPRINT": body["job_id"],
        "GRADE_SLIP": body["job_id"],
        "SITE_PLAN": body["job_id"],
    }
    assert next(row for row in intake_doc_rows if row["document_type"] == "STAKE_DATE")["job_id"] is None

    job_docs = client.get(
        f"/job-documents/jobs/{body['job_id']}/documents",
        headers=_auth_headers(company_id),
    )
    assert job_docs.status_code == 200, job_docs.text
    job_doc_rows = job_docs.json()
    assert [row["document_type"] for row in job_doc_rows] == ["BLUEPRINT", "GRADE_SLIP", "SITE_PLAN"]
    assert {row["job_start_intake_id"] for row in job_doc_rows} == {intake_id}
    assert {row["file_name"] for row in job_doc_rows} == {"blueprints.pdf", "grade slip.pdf", "site plan.pdf"}

    other_company_job_docs = client.get(
        f"/job-documents/jobs/{body['job_id']}/documents",
        headers=_auth_headers(9916),
    )
    assert other_company_job_docs.status_code == 404

    listing = client.get("/job-documents/job-start-intakes", headers=_auth_headers(company_id))
    assert listing.status_code == 200, listing.text
    listed = listing.json()
    assert len(listed) == 1
    assert listed[0]["job_start_intake_id"] == intake_id
    assert listed[0]["job_id"] == body["job_id"]
    assert listed[0]["promotion_status"] == "PROMOTED"
    assert listed[0]["promoted_at"] is not None

    job = client.get(f"/jobs/{body['job_id']}", headers=_auth_headers(company_id))
    assert job.status_code == 200, job.text
    assert job.json()["name"] == "500 Promote Blvd"
    assert job.json()["address_label"] == "500 Promote Blvd"

    db = SessionLocal()
    try:
        row = db.query(Job).filter(Job.company_id == company_id, Job.id == int(body["job_id"])).one()
        assert row.source_job_start_intake_id == intake_id
    finally:
        db.close()


def test_duplicate_promotion_is_idempotent():
    company_id = 9817
    event_id = _create_email_event(company_id, message_suffix="promote-idempotent")

    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Project Address: 600 Idempotent Way\nStake Date: 2026-06-20",
            "attachments": [],
        },
    )
    assert created.status_code == 200, created.text
    intake_id = created.json()["job_start_intake_id"]

    first = client.post(
        f"/job-documents/job-start-intakes/{intake_id}/promote",
        headers=_auth_headers(company_id),
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/job-documents/job-start-intakes/{intake_id}/promote",
        headers=_auth_headers(company_id),
    )
    assert second.status_code == 200, second.text
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["promoted_at"] == first.json()["promoted_at"]

    db = SessionLocal()
    try:
        jobs = (
            db.query(Job)
            .filter(Job.company_id == company_id, Job.source_job_start_intake_id == intake_id)
            .all()
        )
        assert len(jobs) == 1
    finally:
        db.close()


def test_promotion_is_company_scoped():
    owner_company_id = 9818
    other_company_id = 9819
    event_id = _create_email_event(owner_company_id, message_suffix="promote-scope")

    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(owner_company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Project Address: 700 Isolation Ave\nStake Date: 2026-07-01",
            "attachments": [],
        },
    )
    assert created.status_code == 200, created.text
    intake_id = created.json()["job_start_intake_id"]

    promoted = client.post(
        f"/job-documents/job-start-intakes/{intake_id}/promote",
        headers=_auth_headers(other_company_id),
    )
    assert promoted.status_code == 404

    intake_docs = client.get(
        f"/job-documents/job-start-intakes/{intake_id}/documents",
        headers=_auth_headers(other_company_id),
    )
    assert intake_docs.status_code == 404


def test_non_queued_intake_cannot_be_promoted():
    company_id = 9820
    event_id = _create_email_event(company_id, message_suffix="promote-flagged")

    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Project Address: 800 Missing Trigger Ct",
            "attachments": [],
        },
    )
    assert created.status_code == 200, created.text
    intake = created.json()
    assert intake["intake_status"] == "FLAGGED"
    assert intake["queue_trigger_date"] is None

    promoted = client.post(
        f"/job-documents/job-start-intakes/{intake['job_start_intake_id']}/promote",
        headers=_auth_headers(company_id),
    )
    assert promoted.status_code == 409
    assert promoted.json()["detail"] == "Only queued intakes can be promoted"

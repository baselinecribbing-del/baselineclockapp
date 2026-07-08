from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.job_status_history import JobStatusHistory

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "status-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _create_job(company_id: int, name: str = "Status Job") -> dict:
    resp = client.post("/jobs", headers=_auth_headers(company_id), json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_email_event(company_id: int, suffix: str) -> str:
    resp = client.post(
        "/job-documents/email-ingestion-events",
        headers=_auth_headers(company_id),
        json={
            "source_message_id": f"status-{company_id}-{suffix}",
            "sender_email": "starts@builder.com",
            "subject": "Status workflow",
            "parse_status": "RECEIVED",
            "raw_metadata": {"builder_name": "Status Builder"},
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["email_ingestion_event_id"])


def test_promotion_creates_job_in_initial_queued_status():
    company_id = 9961
    event_id = _create_email_event(company_id, "promote")

    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Project Address: 33 Status Way\nStake Date: 2026-09-10",
            "attachments": [],
        },
    )
    assert created.status_code == 200, created.text
    intake_id = created.json()["job_start_intake_id"]

    promoted = client.post(
        f"/job-documents/job-start-intakes/{intake_id}/promote",
        headers=_auth_headers(company_id),
    )
    assert promoted.status_code == 200, promoted.text
    job_id = promoted.json()["job_id"]

    job = client.get(f"/jobs/{job_id}", headers=_auth_headers(company_id))
    assert job.status_code == 200, job.text
    assert job.json()["status"] == "QUEUED"


def test_valid_job_status_transitions_succeed():
    company_id = 9962
    created = _create_job(company_id, "Transition Job")
    job_id = created["id"]

    upcoming = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "UPCOMING", "note": "Scheduled start confirmed"},
    )
    assert upcoming.status_code == 200, upcoming.text
    assert upcoming.json()["status"] == "UPCOMING"

    active = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ACTIVE"},
    )
    assert active.status_code == 200, active.text
    assert active.json()["status"] == "ACTIVE"

    on_hold = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ON_HOLD", "note": "Weather delay"},
    )
    assert on_hold.status_code == 200, on_hold.text
    assert on_hold.json()["status"] == "ON_HOLD"

    resumed = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ACTIVE"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "ACTIVE"

    complete = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "COMPLETE"},
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "COMPLETE"


def test_invalid_job_status_transitions_fail_and_complete_cannot_reenter_pipeline():
    company_id = 9963
    created = _create_job(company_id, "Invalid Transition Job")
    job_id = created["id"]

    invalid = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ACTIVE"},
    )
    assert invalid.status_code == 409
    assert "Invalid status transition" in invalid.json()["detail"]

    no_op = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "QUEUED"},
    )
    assert no_op.status_code == 409
    assert no_op.json()["detail"] == "Job is already in the requested status"

    client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "UPCOMING"},
    )
    client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ACTIVE"},
    )
    client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "COMPLETE"},
    )

    back_to_active = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ACTIVE"},
    )
    assert back_to_active.status_code == 409
    assert "Invalid status transition from COMPLETE to ACTIVE" == back_to_active.json()["detail"]


def test_job_list_and_read_expose_status_and_support_status_filter():
    company_id = 9964
    queued = _create_job(company_id, "Queued Job")
    upcoming = _create_job(company_id, "Upcoming Job")

    transitioned = client.post(
        f"/jobs/{upcoming['id']}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "UPCOMING"},
    )
    assert transitioned.status_code == 200, transitioned.text

    listing = client.get("/jobs", headers=_auth_headers(company_id))
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    statuses = {row["id"]: row["status"] for row in rows}
    assert statuses[queued["id"]] == "QUEUED"
    assert statuses[upcoming["id"]] == "UPCOMING"

    filtered = client.get("/jobs", headers=_auth_headers(company_id), params={"status": "UPCOMING"})
    assert filtered.status_code == 200, filtered.text
    filtered_rows = filtered.json()
    assert len(filtered_rows) == 1
    assert filtered_rows[0]["id"] == upcoming["id"]
    assert filtered_rows[0]["status"] == "UPCOMING"

    get_job = client.get(f"/jobs/{upcoming['id']}", headers=_auth_headers(company_id))
    assert get_job.status_code == 200
    assert get_job.json()["status"] == "UPCOMING"


def test_job_status_transitions_are_company_scoped():
    owner_company_id = 9965
    other_company_id = 9966
    created = _create_job(owner_company_id, "Scoped Job")
    job_id = created["id"]

    other = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(other_company_id),
        json={"target_status": "UPCOMING"},
    )
    assert other.status_code == 404


def test_successful_transition_writes_status_history():
    company_id = 9967
    created = _create_job(company_id, "History Write Job")
    job_id = created["id"]

    transitioned = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "UPCOMING"},
    )
    assert transitioned.status_code == 200, transitioned.text

    db = SessionLocal()
    try:
        rows = (
            db.query(JobStatusHistory)
            .filter(
                JobStatusHistory.company_id == company_id,
                JobStatusHistory.job_id == job_id,
            )
            .order_by(JobStatusHistory.id.asc())
            .all()
        )
        assert [(row.from_status, row.to_status) for row in rows] == [
            (None, "QUEUED"),
            ("QUEUED", "UPCOMING"),
        ]
    finally:
        db.close()


def test_invalid_transition_does_not_create_status_history():
    company_id = 9968
    created = _create_job(company_id, "Invalid History Job")
    job_id = created["id"]

    invalid = client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ACTIVE"},
    )
    assert invalid.status_code == 409, invalid.text

    db = SessionLocal()
    try:
        rows = (
            db.query(JobStatusHistory)
            .filter(
                JobStatusHistory.company_id == company_id,
                JobStatusHistory.job_id == job_id,
            )
            .order_by(JobStatusHistory.id.asc())
            .all()
        )
        assert [(row.from_status, row.to_status) for row in rows] == [(None, "QUEUED")]
    finally:
        db.close()


def test_job_status_history_endpoint_is_company_scoped():
    owner_company_id = 9969
    other_company_id = 9970
    created = _create_job(owner_company_id, "Scoped History Job")
    job_id = created["id"]

    history_other = client.get(
        f"/jobs/{job_id}/status-history",
        headers=_auth_headers(other_company_id),
    )
    assert history_other.status_code == 404, history_other.text


def test_job_status_history_endpoint_ordering_is_deterministic():
    company_id = 9971
    created = _create_job(company_id, "Ordered History Job")
    job_id = created["id"]

    client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "UPCOMING"},
    )
    client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ACTIVE"},
    )

    db = SessionLocal()
    try:
        rows = (
            db.query(JobStatusHistory)
            .filter(JobStatusHistory.job_id == job_id)
            .order_by(JobStatusHistory.id.asc())
            .all()
        )
        changed_at = rows[0].changed_at
        for row in rows:
            row.changed_at = changed_at
        db.commit()
    finally:
        db.close()

    history = client.get(
        f"/jobs/{job_id}/status-history",
        headers=_auth_headers(company_id),
    )
    assert history.status_code == 200, history.text
    assert [(row["from_status"], row["to_status"]) for row in history.json()] == [
        (None, "QUEUED"),
        ("QUEUED", "UPCOMING"),
        ("UPCOMING", "ACTIVE"),
    ]


def test_multiple_valid_transitions_produce_multiple_history_rows_in_sequence():
    company_id = 9972
    created = _create_job(company_id, "Sequence History Job")
    job_id = created["id"]

    client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "UPCOMING"},
    )
    client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ACTIVE"},
    )
    client.post(
        f"/jobs/{job_id}/transition",
        headers=_auth_headers(company_id),
        json={"target_status": "ON_HOLD"},
    )

    history = client.get(
        f"/jobs/{job_id}/status-history",
        headers=_auth_headers(company_id),
    )
    assert history.status_code == 200, history.text
    assert [(row["from_status"], row["to_status"]) for row in history.json()] == [
        (None, "QUEUED"),
        ("QUEUED", "UPCOMING"),
        ("UPCOMING", "ACTIVE"),
        ("ACTIVE", "ON_HOLD"),
    ]

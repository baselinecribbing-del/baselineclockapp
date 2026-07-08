from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "workspace-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _create_email_event(company_id: int, suffix: str) -> str:
    resp = client.post(
        "/job-documents/email-ingestion-events",
        headers=_auth_headers(company_id),
        json={
            "source_message_id": f"workspace-{company_id}-{suffix}",
            "sender_email": "starts@builder.com",
            "subject": "New start intake",
            "parse_status": "RECEIVED",
            "raw_metadata": {"builder_name": "Builder Workspace"},
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["email_ingestion_event_id"])


def _promote_job_from_intake(company_id: int) -> tuple[str, int]:
    event_id = _create_email_event(company_id, "job")
    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Project Address: 10 Workspace Lane\nLot 12 Block 4\nStake Date: 2026-08-15",
            "attachments": [
                {"file_name": "blueprints.pdf", "parsed_text": "blueprint package", "storage_key": "https://cdn.example.com/blueprints.pdf"},
                {"file_name": "grade slip.pdf", "parsed_text": "grade slip", "storage_key": "https://cdn.example.com/grade-slip.pdf"},
                {"file_name": "site plan.pdf", "parsed_text": "site plan", "storage_key": "https://cdn.example.com/site-plan.pdf"},
                {"file_name": "stake date.txt", "parsed_text": "stake date 2026-08-15", "storage_key": "https://cdn.example.com/stake-date.txt"},
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
    return intake_id, int(promoted.json()["job_id"])


def _seed_employee_and_scope(company_id: int, job_id: int) -> tuple[int, int]:
    db = SessionLocal()
    try:
        employee = Employee(company_id=company_id, name="Workspace Employee", is_active=True, hourly_rate_cents=3200)
        db.add(employee)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job_id, name="Workspace Scope", is_active=True)
        db.add(scope)
        db.commit()
        return int(employee.id), int(scope.id)
    finally:
        db.close()


def test_job_workspace_retrieval_includes_documents_hazards_photos_and_activity():
    company_id = 9941
    _intake_id, job_id = _promote_job_from_intake(company_id)
    employee_id, scope_id = _seed_employee_and_scope(company_id, job_id)

    hazard = client.post(
        "/foundations/hazard-assessments",
        headers=_auth_headers(company_id),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "completed_by_employee_id": employee_id,
            "assessment_date": "2026-08-16",
            "form_payload": {
                "title": "Excavation issue",
                "description": "Shoring missing on south wall",
                "status": "OPEN",
            },
        },
    )
    assert hazard.status_code == 200, hazard.text
    hazard_id = hazard.json()["hazard_assessment_id"]

    photo = client.post(
        f"/foundations/hazard-assessments/{hazard_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "file_name": "south-wall.jpg",
            "storage_key": "https://cdn.example.com/south-wall.jpg",
            "caption": "South wall exposure",
        },
    )
    assert photo.status_code == 200, photo.text

    activity = client.post(
        "/foundations/activity",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "activity_type": "ISSUE_REPORTED",
            "notes": "Hazard reported to site lead.",
        },
    )
    assert activity.status_code == 200, activity.text

    workspace = client.get(f"/jobs/{job_id}/workspace", headers=_auth_headers(company_id))
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()

    assert body["job"] == {
        "id": job_id,
        "builder_name": "Builder Workspace",
        "project_address": "10 Workspace Lane",
        "lot_block": "Lot 12 Block 4",
        "stake_date": "2026-08-15",
        "queue_trigger_date": "2026-08-15",
        "status": "QUEUED",
    }

    assert {row["type"] for row in body["blueprints"]} == {"BLUEPRINT", "GRADE_SLIP", "SITE_PLAN"}
    assert {row["file_name"] for row in body["blueprints"]} == {"blueprints.pdf", "grade slip.pdf", "site plan.pdf"}

    assert len(body["documents"]) == 1
    assert body["documents"][0]["type"] == "STAKE_DATE"
    assert body["documents"][0]["file_name"] == "stake date.txt"

    assert len(body["hazards"]) == 1
    assert body["hazards"][0]["hazard_id"] == hazard_id
    assert body["hazards"][0]["title"] == "Excavation issue"
    assert body["hazards"][0]["description"] == "Shoring missing on south wall"
    assert body["hazards"][0]["status"] == "OPEN"

    assert len(body["hazard_photos"]) == 1
    assert body["hazard_photos"][0]["hazard_id"] == hazard_id
    assert body["hazard_photos"][0]["file_name"] == "south-wall.jpg"
    assert body["hazard_photos"][0]["storage_key"] == "https://cdn.example.com/south-wall.jpg"

    assert len(body["activity"]) == 1
    assert body["activity"][0]["type"] == "ISSUE_REPORTED"
    assert body["activity"][0]["description"] == "Hazard reported to site lead."


def test_job_workspace_enforces_company_isolation_and_404s():
    owner_company_id = 9942
    other_company_id = 9943
    _intake_id, job_id = _promote_job_from_intake(owner_company_id)

    other_company = client.get(f"/jobs/{job_id}/workspace", headers=_auth_headers(other_company_id))
    assert other_company.status_code == 404

    missing = client.get("/jobs/999999/workspace", headers=_auth_headers(owner_company_id))
    assert missing.status_code == 404

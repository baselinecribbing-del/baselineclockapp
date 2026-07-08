from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "upload-user") -> dict[str, str]:
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
            "source_message_id": f"upload-{company_id}-{suffix}",
            "sender_email": "starts@builder.com",
            "subject": "Upload transport start",
            "parse_status": "RECEIVED",
            "raw_metadata": {"builder_name": "Upload Builder"},
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["email_ingestion_event_id"])


def _promote_job(company_id: int) -> tuple[str, int]:
    event_id = _create_email_event(company_id, "promote")
    created = client.post(
        "/job-documents/job-start-intakes/from-email",
        headers=_auth_headers(company_id),
        json={
            "email_ingestion_event_id": event_id,
            "parsed_text": "Project Address: 22 Upload Road\nStake Date: 2026-09-01",
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
    return intake_id, int(promoted.json()["job_id"])


def _seed_employee_and_scope(company_id: int, job_id: int) -> tuple[int, int]:
    db = SessionLocal()
    try:
        employee = Employee(company_id=company_id, name="Upload Employee", is_active=True, hourly_rate_cents=3200)
        db.add(employee)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job_id, name="Upload Scope", is_active=True)
        db.add(scope)
        db.commit()
        return int(employee.id), int(scope.id)
    finally:
        db.close()


def _create_hazard_assessment(company_id: int, job_id: int, scope_id: int, employee_id: int) -> str:
    resp = client.post(
        "/foundations/hazard-assessments",
        headers=_auth_headers(company_id),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "completed_by_employee_id": employee_id,
            "assessment_date": "2026-09-02",
            "form_payload": {"title": "Upload hazard"},
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["hazard_assessment_id"])


def test_job_document_upload_prepare_returns_valid_transport_metadata_when_configured(monkeypatch):
    company_id = 9951
    intake_id, _job_id = _promote_job(company_id)
    monkeypatch.setenv("DOCUMENT_UPLOAD_TARGET_BASE_URL", "https://uploads.example.com/direct")

    prepared = client.post(
        "/job-documents/uploads/prepare",
        headers=_auth_headers(company_id),
        json={
            "file_name": "foundation-blueprint.pdf",
            "content_type": "application/pdf",
            "document_type": "BLUEPRINT",
            "intake_id": intake_id,
        },
    )
    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    assert body["storage_key"].startswith(f"job-documents/company-{company_id}/intakes/{intake_id}/")
    assert body["upload_url"].startswith("https://uploads.example.com/direct/job-documents/")
    assert body["available"] is True
    assert body["reason"] is None


def test_job_document_upload_prepare_returns_honest_unavailable_when_not_configured(monkeypatch):
    company_id = 9952
    intake_id, _job_id = _promote_job(company_id)
    monkeypatch.delenv("DOCUMENT_UPLOAD_TARGET_BASE_URL", raising=False)

    prepared = client.post(
        "/job-documents/uploads/prepare",
        headers=_auth_headers(company_id),
        json={
            "file_name": "site-plan.pdf",
            "content_type": "application/pdf",
            "document_type": "SITE_PLAN",
            "intake_id": intake_id,
        },
    )
    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    assert body["storage_key"].startswith(f"job-documents/company-{company_id}/intakes/{intake_id}/")
    assert body["upload_url"] is None
    assert body["available"] is False
    assert body["reason"] == "Upload target generation is not configured"


def test_finalized_job_document_linkage_works_for_promoted_intake():
    company_id = 9953
    intake_id, job_id = _promote_job(company_id)

    prepared = client.post(
        "/job-documents/uploads/prepare",
        headers=_auth_headers(company_id),
        json={
            "file_name": "grade-slip.pdf",
            "content_type": "application/pdf",
            "document_type": "GRADE_SLIP",
            "intake_id": intake_id,
        },
    )
    assert prepared.status_code == 200, prepared.text
    storage_key = prepared.json()["storage_key"]

    created = client.post(
        "/job-documents",
        headers=_auth_headers(company_id),
        json={
            "file_name": "grade-slip.pdf",
            "storage_key": storage_key,
            "document_type": "GRADE_SLIP",
            "intake_id": intake_id,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["job_start_intake_id"] == intake_id
    assert body["job_id"] == job_id
    assert body["document_type"] == "GRADE_SLIP"

    intake_docs = client.get(
        f"/job-documents/job-start-intakes/{intake_id}/documents",
        headers=_auth_headers(company_id),
    )
    assert intake_docs.status_code == 200, intake_docs.text
    assert any(row["document_id"] == body["document_id"] for row in intake_docs.json())

    job_docs = client.get(
        f"/job-documents/jobs/{job_id}/documents",
        headers=_auth_headers(company_id),
    )
    assert job_docs.status_code == 200, job_docs.text
    assert any(row["document_id"] == body["document_id"] for row in job_docs.json())


def test_finalized_hazard_photo_linkage_works():
    company_id = 9954
    _intake_id, job_id = _promote_job(company_id)
    employee_id, scope_id = _seed_employee_and_scope(company_id, job_id)
    hazard_assessment_id = _create_hazard_assessment(company_id, job_id, scope_id, employee_id)

    prepared = client.post(
        "/foundations/hazard-assessment-photos/uploads/prepare",
        headers=_auth_headers(company_id),
        json={
            "file_name": "wall-crack.jpg",
            "content_type": "image/jpeg",
            "hazard_assessment_id": hazard_assessment_id,
            "document_type": "ISSUE_PHOTO",
        },
    )
    assert prepared.status_code == 200, prepared.text
    storage_key = prepared.json()["storage_key"]

    created = client.post(
        f"/foundations/hazard-assessments/{hazard_assessment_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "file_name": "wall-crack.jpg",
            "storage_key": storage_key,
            "caption": "North wall crack",
        },
    )
    assert created.status_code == 200, created.text
    photo = created.json()
    assert photo["hazard_assessment_id"] == hazard_assessment_id
    assert photo["storage_key"] == storage_key

    listing = client.get(
        f"/foundations/hazard-assessments/{hazard_assessment_id}/photos",
        headers=_auth_headers(company_id),
    )
    assert listing.status_code == 200, listing.text
    assert any(row["photo_id"] == photo["photo_id"] for row in listing.json())


def test_upload_transport_company_isolation_and_unsupported_types_are_rejected():
    owner_company_id = 9955
    other_company_id = 9956
    intake_id, job_id = _promote_job(owner_company_id)
    employee_id, scope_id = _seed_employee_and_scope(owner_company_id, job_id)
    hazard_assessment_id = _create_hazard_assessment(owner_company_id, job_id, scope_id, employee_id)

    other_prepare = client.post(
        "/job-documents/uploads/prepare",
        headers=_auth_headers(other_company_id),
        json={
            "file_name": "blueprint.pdf",
            "content_type": "application/pdf",
            "document_type": "BLUEPRINT",
            "intake_id": intake_id,
        },
    )
    assert other_prepare.status_code == 404

    other_hazard_prepare = client.post(
        "/foundations/hazard-assessment-photos/uploads/prepare",
        headers=_auth_headers(other_company_id),
        json={
            "file_name": "issue.jpg",
            "content_type": "image/jpeg",
            "hazard_assessment_id": hazard_assessment_id,
            "document_type": "ISSUE_PHOTO",
        },
    )
    assert other_hazard_prepare.status_code == 404

    unsupported = client.post(
        "/job-documents/uploads/prepare",
        headers=_auth_headers(owner_company_id),
        json={
            "file_name": "permit.pdf",
            "content_type": "application/pdf",
            "document_type": "PERMIT",
            "job_id": job_id,
        },
    )
    assert unsupported.status_code == 422

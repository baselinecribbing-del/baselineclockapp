from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.job_document import JobDocument
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "field-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_refs(company_id: int, suffix: str = "A") -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        employee = Employee(company_id=company_id, name=f"Emp {suffix}", is_active=True, hourly_rate_cents=3200)
        db.add(employee)
        db.flush()

        job = Job(company_id=company_id, name=f"Job {suffix}", is_active=True)
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Scope {suffix}", is_active=True)
        db.add(scope)
        db.commit()
        return int(employee.id), int(job.id), int(scope.id)
    finally:
        db.close()


def _seed_job_document(company_id: int, job_id: int, scope_id: int | None, name_suffix: str) -> str:
    db = SessionLocal()
    try:
        row = JobDocument(
            company_id=company_id,
            job_id=job_id,
            scope_id=scope_id,
            document_type="BLUEPRINT",
            file_name=f"drawing-{name_suffix}.pdf",
            storage_key=f"https://cdn.example.com/{name_suffix}.pdf",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.job_document_id)
    finally:
        db.close()


def test_create_activity_log_success_and_company_scoping():
    c1 = 9101
    c2 = 9102
    employee_id, job_id, scope_id = _seed_refs(c1, "Act")
    _seed_refs(c2, "Act2")

    create = client.post(
        "/foundations/activity",
        headers=_auth_headers(c1),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "activity_type": "CLOCK_IN",
            "notes": "On site",
        },
    )
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["company_id"] == c1
    assert created["activity_type"] == "CLOCK_IN"

    c1_list = client.get("/foundations/activity", headers=_auth_headers(c1))
    assert c1_list.status_code == 200, c1_list.text
    assert len(c1_list.json()) == 1

    c2_list = client.get("/foundations/activity", headers=_auth_headers(c2))
    assert c2_list.status_code == 200, c2_list.text
    assert c2_list.json() == []


def test_photo_activity_validation_and_success():
    company_id = 9201
    employee_id, job_id, scope_id = _seed_refs(company_id, "Photo")

    missing_photo_url = client.post(
        "/foundations/activity",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "activity_type": "JOB_PROGRESS_PHOTO",
            "notes": "Framing progress",
        },
    )
    assert missing_photo_url.status_code == 422

    create_photo = client.post(
        "/foundations/activity",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "activity_type": "JOB_PROGRESS_PHOTO",
            "notes": "Framing progress",
            "photo_url": "https://cdn.example.com/progress-1.jpg",
        },
    )
    assert create_photo.status_code == 200, create_photo.text
    assert create_photo.json()["photo_url"] == "https://cdn.example.com/progress-1.jpg"


def test_issue_reporting_requires_notes_and_succeeds_with_notes():
    company_id = 9301
    employee_id, job_id, scope_id = _seed_refs(company_id, "Issue")

    missing_notes = client.post(
        "/foundations/activity",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "activity_type": "ISSUE_REPORTED",
        },
    )
    assert missing_notes.status_code == 422

    create_issue = client.post(
        "/foundations/activity",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "activity_type": "ISSUE_REPORTED",
            "notes": "Missing material at east pad.",
        },
    )
    assert create_issue.status_code == 200, create_issue.text
    assert create_issue.json()["activity_type"] == "ISSUE_REPORTED"
    assert create_issue.json()["notes"] == "Missing material at east pad."


def test_activity_filtering_by_type_and_ids_and_date_range():
    company_id = 9401
    employee_id, job_id, scope_id = _seed_refs(company_id, "Filter")

    client.post(
        "/foundations/activity",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "activity_type": "CLOCK_IN",
            "notes": "Start",
        },
    )
    client.post(
        "/foundations/activity",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "activity_type": "ISSUE_REPORTED",
            "notes": "Blocked access",
        },
    )

    filtered = client.get(
        "/foundations/activity",
        headers=_auth_headers(company_id),
        params={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "activity_type": "ISSUE_REPORTED",
            "date_from": date(2026, 1, 1).isoformat(),
            "date_to": date(2026, 12, 31).isoformat(),
        },
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["activity_type"] == "ISSUE_REPORTED"


def test_foundations_job_documents_list_filters_and_scoping():
    c1 = 9501
    c2 = 9502

    _e1, job_id, scope_id = _seed_refs(c1, "Doc")
    _e2, c2_job_id, c2_scope_id = _seed_refs(c2, "Doc2")

    _seed_job_document(c1, job_id, scope_id, "c1")
    _seed_job_document(c2, c2_job_id, c2_scope_id, "c2")

    filtered = client.get(
        "/foundations/job-documents",
        headers=_auth_headers(c1),
        params={"job_id": job_id, "scope_id": scope_id},
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["filename"] == "drawing-c1.pdf"
    assert rows[0]["download_url"] == "https://cdn.example.com/c1.pdf"

    c2_list = client.get("/foundations/job-documents", headers=_auth_headers(c2))
    assert c2_list.status_code == 200
    assert len(c2_list.json()) == 1

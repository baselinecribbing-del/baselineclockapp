from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.hazard_assessment import HazardAssessment
from app.models.job import Job
from app.models.job_document import JobDocument
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "doc-access-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_job(company_id: int, suffix: str) -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        employee = Employee(company_id=company_id, name=f"Employee {suffix}", is_active=True, hourly_rate_cents=3300)
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


def _seed_job_document(*, company_id: int, job_id: int, document_type: str, file_name: str, storage_key: str | None) -> str:
    db = SessionLocal()
    try:
        row = JobDocument(
            company_id=company_id,
            job_id=job_id,
            document_type=document_type,
            file_name=file_name,
            storage_key=storage_key,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.job_document_id)
    finally:
        db.close()


def _seed_hazard_assessment(company_id: int, suffix: str) -> tuple[str, int]:
    employee_id, job_id, scope_id = _seed_job(company_id, suffix)
    db = SessionLocal()
    try:
        row = HazardAssessment(
            company_id=company_id,
            job_id=job_id,
            scope_id=scope_id,
            completed_by_employee_id=employee_id,
            assessment_date=date(2026, 7, 20),
            form_payload={"issues_found": True},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.hazard_assessment_id), int(job_id)
    finally:
        db.close()


def test_job_document_access_contract_returns_direct_url_when_resolvable():
    company_id = 9931
    _employee_id, job_id, _scope_id = _seed_job(company_id, "Direct")
    document_id = _seed_job_document(
        company_id=company_id,
        job_id=job_id,
        document_type="BLUEPRINT",
        file_name="foundation-plan.pdf",
        storage_key="https://cdn.example.com/foundation-plan.pdf",
    )

    listing = client.get(f"/job-documents/jobs/{job_id}/documents", headers=_auth_headers(company_id))
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["document_id"] == document_id
    assert rows[0]["job_document_id"] == document_id

    access = client.get(f"/job-documents/records/{document_id}/access", headers=_auth_headers(company_id))
    assert access.status_code == 200, access.text
    body = access.json()
    assert body["document_id"] == document_id
    assert body["access_type"] == "direct_url"
    assert body["available"] is True
    assert body["file_url"] == "https://cdn.example.com/foundation-plan.pdf"
    assert body["download_url"] is None
    assert body["file_name"] == "foundation-plan.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["reason"] is None


def test_job_document_access_contract_returns_unavailable_honestly():
    company_id = 9932
    _employee_id, job_id, _scope_id = _seed_job(company_id, "Unavailable")
    document_id = _seed_job_document(
        company_id=company_id,
        job_id=job_id,
        document_type="SITE_PLAN",
        file_name="site-plan.pdf",
        storage_key="s3://private-bucket/site-plan.pdf",
    )

    access = client.get(f"/job-documents/records/{document_id}/access", headers=_auth_headers(company_id))
    assert access.status_code == 200, access.text
    body = access.json()
    assert body["document_id"] == document_id
    assert body["access_type"] == "unavailable"
    assert body["available"] is False
    assert body["file_url"] is None
    assert body["reason"] == "Storage reference cannot be resolved into a usable file URL"


def test_hazard_issue_photo_access_contract_works():
    company_id = 9933
    hazard_assessment_id, _job_id = _seed_hazard_assessment(company_id, "Photo")

    created = client.post(
        f"/foundations/hazard-assessments/{hazard_assessment_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "file_name": "issue-photo.jpg",
            "storage_key": "https://cdn.example.com/issue-photo.jpg",
            "caption": "Cracked form edge",
        },
    )
    assert created.status_code == 200, created.text
    photo = created.json()
    assert photo["photo_id"] == photo["job_document_id"]

    access = client.get(
        f"/foundations/hazard-assessment-photos/{photo['photo_id']}/access",
        headers=_auth_headers(company_id),
    )
    assert access.status_code == 200, access.text
    body = access.json()
    assert body["photo_id"] == photo["photo_id"]
    assert body["access_type"] == "direct_url"
    assert body["available"] is True
    assert body["file_url"] == "https://cdn.example.com/issue-photo.jpg"
    assert body["content_type"] == "image/jpeg"


def test_document_access_contract_is_company_scoped():
    owner_company_id = 9934
    other_company_id = 9935
    _employee_id, job_id, _scope_id = _seed_job(owner_company_id, "Scope")
    document_id = _seed_job_document(
        company_id=owner_company_id,
        job_id=job_id,
        document_type="GRADE_SLIP",
        file_name="grade-slip.pdf",
        storage_key="https://cdn.example.com/grade-slip.pdf",
    )
    hazard_assessment_id, _ = _seed_hazard_assessment(owner_company_id, "ScopePhoto")
    created_photo = client.post(
        f"/foundations/hazard-assessments/{hazard_assessment_id}/photos",
        headers=_auth_headers(owner_company_id),
        json={
            "file_name": "issue.jpg",
            "storage_key": "https://cdn.example.com/issue.jpg",
        },
    )
    assert created_photo.status_code == 200, created_photo.text
    photo_id = created_photo.json()["photo_id"]

    other_doc_access = client.get(
        f"/job-documents/records/{document_id}/access",
        headers=_auth_headers(other_company_id),
    )
    assert other_doc_access.status_code == 404

    other_photo_access = client.get(
        f"/foundations/hazard-assessment-photos/{photo_id}/access",
        headers=_auth_headers(other_company_id),
    )
    assert other_photo_access.status_code == 404


def test_document_access_contract_handles_invalid_ids():
    company_id = 9936

    invalid_doc = client.get("/job-documents/records/not-a-real-document/access", headers=_auth_headers(company_id))
    assert invalid_doc.status_code == 404

    invalid_photo = client.get(
        "/foundations/hazard-assessment-photos/not-a-real-photo/access",
        headers=_auth_headers(company_id),
    )
    assert invalid_photo.status_code == 404

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "hazard-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_refs(company_id: int, suffix: str) -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        employee = Employee(company_id=company_id, name=f"Employee {suffix}", is_active=True, hourly_rate_cents=3200)
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


def _create_hazard_assessment(company_id: int, suffix: str = "A") -> dict:
    employee_id, job_id, scope_id = _seed_refs(company_id, suffix)
    resp = client.post(
        "/foundations/hazard-assessments",
        headers=_auth_headers(company_id),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "completed_by_employee_id": employee_id,
            "assessment_date": "2026-07-10",
            "form_payload": {"issues_found": True, "summary": "Uneven trench wall"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    body["employee_id"] = employee_id
    body["scope_id"] = scope_id
    return body


def test_hazard_assessment_issue_photos_can_be_linked_and_retrieved():
    company_id = 9921
    assessment = _create_hazard_assessment(company_id, "Photo")

    create_1 = client.post(
        f"/foundations/hazard-assessments/{assessment['hazard_assessment_id']}/photos",
        headers=_auth_headers(company_id),
        json={
            "file_name": "trench-wall-1.jpg",
            "storage_key": "s3://hazards/trench-wall-1.jpg",
            "caption": "North edge sloughing",
        },
    )
    assert create_1.status_code == 200, create_1.text
    body_1 = create_1.json()
    assert body_1["document_type"] == "ISSUE_PHOTO"
    assert body_1["hazard_assessment_id"] == assessment["hazard_assessment_id"]
    assert body_1["job_id"] == assessment["job_id"]
    assert body_1["caption"] == "North edge sloughing"

    create_2 = client.post(
        f"/foundations/hazard-assessments/{assessment['hazard_assessment_id']}/photos",
        headers=_auth_headers(company_id),
        json={
            "file_name": "trench-wall-2.jpg",
            "storage_key": "s3://hazards/trench-wall-2.jpg",
        },
    )
    assert create_2.status_code == 200, create_2.text

    listing = client.get(
        f"/foundations/hazard-assessments/{assessment['hazard_assessment_id']}/photos",
        headers=_auth_headers(company_id),
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 2
    assert [row["document_type"] for row in rows] == ["ISSUE_PHOTO", "ISSUE_PHOTO"]
    assert {row["file_name"] for row in rows} == {"trench-wall-1.jpg", "trench-wall-2.jpg"}
    assert {row["storage_key"] for row in rows} == {
        "s3://hazards/trench-wall-1.jpg",
        "s3://hazards/trench-wall-2.jpg",
    }


def test_hazard_assessment_photo_endpoints_are_company_scoped():
    owner_company_id = 9922
    other_company_id = 9923
    assessment = _create_hazard_assessment(owner_company_id, "Scope")

    create_other = client.post(
        f"/foundations/hazard-assessments/{assessment['hazard_assessment_id']}/photos",
        headers=_auth_headers(other_company_id),
        json={
            "file_name": "blocked.jpg",
            "storage_key": "s3://hazards/blocked.jpg",
        },
    )
    assert create_other.status_code == 404

    list_other = client.get(
        f"/foundations/hazard-assessments/{assessment['hazard_assessment_id']}/photos",
        headers=_auth_headers(other_company_id),
    )
    assert list_other.status_code == 404

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int) -> dict:
    resp = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    data = resp.json()
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {data['access_token']}"}


def _seed_employee_job_scope(company_id: int, suffix: str) -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        employee = Employee(company_id=company_id, name=f"Emp {suffix}", is_active=True, hourly_rate_cents=3000)
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


def test_jobs_coordinate_first_fields_persist_and_patch():
    company_id = 9301

    create = client.post(
        "/jobs",
        headers=_auth_headers(company_id),
        json={
            "name": "Tower A",
            "address_label": "South Gate Laydown",
            "site_lat": 51.045,
            "site_lng": -114.057,
        },
    )
    assert create.status_code == 200, create.text
    created = create.json()
    job_id = created["id"]

    assert created["address_label"] == "South Gate Laydown"
    assert created["site_lat"] == 51.045
    assert created["site_lng"] == -114.057
    assert created["site_radius_m"] == 500

    patch = client.patch(
        f"/jobs/{job_id}",
        headers=_auth_headers(company_id),
        json={
            "address_label": "South Gate Laydown Updated",
            "site_lat": 51.046,
            "site_lng": -114.058,
            "site_radius_m": 650,
        },
    )
    assert patch.status_code == 200, patch.text
    patched = patch.json()
    assert patched["address_label"] == "South Gate Laydown Updated"
    assert patched["site_lat"] == 51.046
    assert patched["site_lng"] == -114.058
    assert patched["site_radius_m"] == 650


def test_clock_in_uses_default_geofence_radius_500m_when_radius_missing():
    company_id = 9302
    employee_id, job_id, scope_id = _seed_employee_job_scope(company_id, "GEOFENCE-DEFAULT")

    patch_job = client.patch(
        f"/jobs/{job_id}",
        headers=_auth_headers(company_id),
        json={
            "address_label": "Coordinate First Site",
            "site_lat": 51.0,
            "site_lng": -114.0,
        },
    )
    assert patch_job.status_code == 200, patch_job.text
    assert patch_job.json()["site_radius_m"] == 500

    # ~611m north of site -> outside 500m default radius
    out_of_geofence = client.post(
        "/time_entries/clock_in",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "clock_in_lat": 51.0055,
            "clock_in_lng": -114.0,
        },
    )
    assert out_of_geofence.status_code == 409, out_of_geofence.text
    body = out_of_geofence.json()
    assert body["radius_m"] == 500
    assert body["distance_m"] > 500


def test_clock_in_explicit_radius_override_still_applies():
    company_id = 9303
    employee_id, job_id, scope_id = _seed_employee_job_scope(company_id, "GEOFENCE-OVERRIDE")

    patch_job = client.patch(
        f"/jobs/{job_id}",
        headers=_auth_headers(company_id),
        json={
            "site_lat": 51.0,
            "site_lng": -114.0,
            "site_radius_m": 2000,
        },
    )
    assert patch_job.status_code == 200, patch_job.text
    assert patch_job.json()["site_radius_m"] == 2000

    # ~1111m north of site -> should be allowed under 2000m override
    in_override_radius = client.post(
        "/time_entries/clock_in",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "clock_in_lat": 51.01,
            "clock_in_lng": -114.0,
        },
    )
    assert in_override_radius.status_code == 200, in_override_radius.text

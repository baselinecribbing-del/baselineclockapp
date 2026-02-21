from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.time_entry import TimeEntry
from app.models.workflow_execution import WorkflowExecution

client = TestClient(app)


def _auth_headers(company_id: int) -> dict:
    resp = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert isinstance(data, dict), f"token response not a JSON object: {data}"
    assert "access_token" in data, f"token response missing access_token: {data}"
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {data['access_token']}"}


def _db():
    return SessionLocal()


def _ensure_no_active(company_id: int, employee_id: int):
    db = _db()
    try:
        db.query(TimeEntry).filter(
            TimeEntry.company_id == company_id,
            TimeEntry.employee_id == employee_id,
            TimeEntry.status == "active",
        ).delete(synchronize_session=False)
        db.query(WorkflowExecution).filter(
            WorkflowExecution.status == "in_progress",
            WorkflowExecution.context["company_id"].as_integer() == int(company_id),
            WorkflowExecution.context["employee_id"].as_integer() == int(employee_id),
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _insert_active(company_id: int, employee_id: int, job_id: int, scope_id: int):
    db = _db()
    try:
        row = TimeEntry(
            time_entry_id=str(uuid4()),
            company_id=company_id,
            employee_id=employee_id,
            job_id=job_id,
            scope_id=scope_id,
            started_at=datetime.utcnow(),
            ended_at=None,
            status="active",
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def test_clock_out_flow_requires_active_time_entry(employee_factory, job_factory, scope_factory):
    company_id = 9001
    employee = employee_factory(company_id=company_id)
    job = job_factory(company_id=company_id)
    scope = scope_factory(company_id=company_id, job_id=job.id)
    employee_id = employee.id

    _ensure_no_active(company_id, employee_id)

    r = client.post(
        "/preview/start",
        headers=_auth_headers(company_id),
        json={
            "flow_name": "clock_out_flow",
            "company_id": company_id,
            "employee_id": employee_id,
            "job_id": job.id,
            "scope_id": scope.id,
        },
    )
    assert r.status_code == 400
    assert "No active time entry found" in r.json().get("detail", "")


def test_clock_out_flow_starts_when_active_time_entry_exists(employee_factory, job_factory, scope_factory):
    company_id = 9011
    employee = employee_factory(company_id=company_id)
    job = job_factory(company_id=company_id)
    scope = scope_factory(company_id=company_id, job_id=job.id)
    employee_id = employee.id

    _ensure_no_active(company_id, employee_id)
    _insert_active(company_id, employee_id, job.id, scope.id)

    r = client.post(
        "/preview/start",
        headers=_auth_headers(company_id),
        json={
            "flow_name": "clock_out_flow",
            "company_id": company_id,
            "employee_id": employee_id,
            "job_id": job.id,
            "scope_id": scope.id,
        },
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["flow_name"] == "clock_out_flow"
    assert "execution_id" in payload

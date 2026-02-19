from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.time_entry import TimeEntry
from app.models.workflow_execution import WorkflowExecution

client = TestClient(app)


def _auth_headers(company_id: int) -> dict:
    r = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    token = r.json()["access_token"]
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {token}"}


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


def _insert_active(company_id: int, employee_id: int):
    db = _db()
    try:
        row = TimeEntry(
            time_entry_id=str(uuid4()),
            company_id=company_id,
            employee_id=employee_id,
            job_id=1,
            scope_id=1,
            started_at=datetime.utcnow(),
            ended_at=None,
            status="active",
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def test_clock_out_flow_requires_active_time_entry():
    company_id = 9001
    employee_id = 9002

    _ensure_no_active(company_id, employee_id)

    r = client.post(
        "/preview/start",
        headers=_auth_headers(company_id),
        json={
            "flow_name": "clock_out_flow",
            "company_id": company_id,
            "employee_id": employee_id,
            "job_id": 1,
            "scope_id": 1,
        },
    )
    assert r.status_code == 400
    assert "No active time entry found" in r.json().get("detail", "")


def test_clock_out_flow_starts_when_active_time_entry_exists():
    company_id = 9011
    employee_id = 9012

    _ensure_no_active(company_id, employee_id)
    _insert_active(company_id, employee_id)

    r = client.post(
        "/preview/start",
        headers=_auth_headers(company_id),
        json={
            "flow_name": "clock_out_flow",
            "company_id": company_id,
            "employee_id": employee_id,
            "job_id": 1,
            "scope_id": 1,
        },
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["flow_name"] == "clock_out_flow"
    assert "execution_id" in payload

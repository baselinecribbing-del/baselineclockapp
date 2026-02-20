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


def _insert_active_time_entry(company_id: int, employee_id: int):
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
        db.refresh(row)
        return row.time_entry_id
    finally:
        db.close()


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


def _get_execution(execution_id: str) -> WorkflowExecution:
    db = _db()
    try:
        ex = db.query(WorkflowExecution).filter(WorkflowExecution.execution_id == execution_id).first()
        assert ex is not None
        return ex
    finally:
        db.close()


def _count_active_time_entries(company_id: int, employee_id: int) -> int:
    db = _db()
    try:
        return (
            db.query(TimeEntry)
            .filter(
                TimeEntry.company_id == company_id,
                TimeEntry.employee_id == employee_id,
                TimeEntry.status == "active",
            )
            .count()
        )
    finally:
        db.close()


def test_workflow_rollback_when_time_engine_fails_on_completion():
    company_id = 7777
    employee_id = 8888
    job_id = 1
    scope_id = 1

    _ensure_no_active(company_id, employee_id)
    headers = _auth_headers(company_id)

    r = client.post(
        "/preview/start",
        headers=headers,
        json={
            "flow_name": "clock_in_flow",
            "company_id": company_id,
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
        },
    )
    assert r.status_code == 200
    execution_id = r.json()["execution_id"]

    r = client.post(
        f"/preview/{execution_id}/submit",
        headers=headers,
        json={"value": "ok"},
    )
    assert r.status_code == 200
    r = client.post(
        f"/preview/{execution_id}/advance",
        headers=headers,
    )
    assert r.status_code == 200

    r = client.post(
        f"/preview/{execution_id}/submit",
        headers=headers,
        json={"value": "ok"},
    )
    assert r.status_code == 200
    r = client.post(
        f"/preview/{execution_id}/advance",
        headers=headers,
    )
    assert r.status_code == 200

    r = client.post(
        f"/preview/{execution_id}/submit",
        headers=headers,
        json={"value": "ok"},
    )
    assert r.status_code == 200

    _insert_active_time_entry(company_id=company_id, employee_id=employee_id)
    assert _count_active_time_entries(company_id, employee_id) == 1

    r = client.post(
        f"/preview/{execution_id}/advance",
        headers=headers,
    )
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert "Active time entry already exists" in detail

    ex = _get_execution(execution_id)
    assert ex.status == "in_progress"
    assert ex.current_step_id == "confirm_scope"

    assert _count_active_time_entries(company_id, employee_id) == 1

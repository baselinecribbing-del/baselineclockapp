from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
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


def _run_flow_to_completion(
    flow_name: str,
    company_id: int,
    employee_id: int,
    job_id: int,
    scope_id: int,
) -> str:
    headers = _auth_headers(company_id)

    r = client.post(
        "/preview/start",
        headers=headers,
        json={
            "flow_name": flow_name,
            "company_id": company_id,
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
        },
    )
    assert r.status_code == 200
    execution_id = r.json()["execution_id"]

    while True:
        status_r = client.get(f"/preview/{execution_id}", headers=headers)
        assert status_r.status_code == 200
        payload = status_r.json()

        if payload["status"] == "completed":
            break

        submit_r = client.post(
            f"/preview/{execution_id}/submit",
            headers=headers,
            json={"value": "ok"},
        )
        assert submit_r.status_code == 200

        advance_r = client.post(
            f"/preview/{execution_id}/advance",
            headers=headers,
        )
        assert advance_r.status_code == 200

    return execution_id


def _ensure_no_active(company_id: int, employee_id: int):
    db = SessionLocal()
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


def test_clock_in_creates_active_time_entry():
    company_id = 7101
    employee_id = 8101
    job_id = 1
    scope_id = 1

    _ensure_no_active(company_id, employee_id)

    headers = _auth_headers(company_id)
    pre = client.get(f"/time_entries/active?employee_id={employee_id}", headers=headers)
    assert pre.status_code == 404

    _run_flow_to_completion(
        flow_name="clock_in_flow",
        company_id=company_id,
        employee_id=employee_id,
        job_id=job_id,
        scope_id=scope_id,
    )

    r = client.get(f"/time_entries/active?employee_id={employee_id}", headers=headers)
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "active"
    assert payload["ended_at"] is None
    assert payload["company_id"] == company_id
    assert payload["employee_id"] == employee_id
    assert payload["job_id"] == job_id
    assert payload["scope_id"] == scope_id

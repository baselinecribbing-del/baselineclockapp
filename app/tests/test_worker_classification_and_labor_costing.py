from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.pay_period import PayPeriod
from app.models.scope import Scope
from app.models.time_entry import TimeEntry
from app.services.deduction_engine import compute_deduction_amounts

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "test-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_job_scope(company_id: int, suffix: str) -> tuple[int, int]:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"Job {suffix}", is_active=True)
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Scope {suffix}", is_active=True)
        db.add(scope)
        db.commit()

        return int(job.id), int(scope.id)
    finally:
        db.close()


def _seed_pay_period(company_id: int, pay_period_id: str) -> None:
    db = SessionLocal()
    try:
        db.add(
            PayPeriod(
                pay_period_id=pay_period_id,
                company_id=company_id,
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 14),
                status="POSTED",
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_approved_time_entry(
    *,
    company_id: int,
    employee_id: int,
    job_id: int,
    scope_id: int,
    time_entry_id: str,
    hours: int,
) -> None:
    started_at = datetime(2026, 3, 6, 8, 0, 0, tzinfo=timezone.utc)
    ended_at = started_at + timedelta(hours=hours)

    db = SessionLocal()
    try:
        db.add(
            TimeEntry(
                time_entry_id=time_entry_id,
                company_id=company_id,
                employee_id=employee_id,
                job_id=job_id,
                scope_id=scope_id,
                started_at=started_at,
                ended_at=ended_at,
                status="completed",
                approval_status="approved",
            )
        )
        db.commit()
    finally:
        db.close()


def test_employee_labor_class_defaults_to_payroll_employee():
    company_id = 9501

    create = client.post(
        "/employees",
        headers=_auth_headers(company_id),
        json={"name": "Default Class Employee"},
    )
    assert create.status_code == 200, create.text
    body = create.json()

    assert body["labor_class"] == "PAYROLL_EMPLOYEE"
    assert body["include_wcb_cost"] is True
    assert body["include_ei_cost"] is True
    assert body["include_tax_cost"] is True
    assert body["requires_payroll"] is True


def test_casual_cash_and_subcontractor_exclude_payroll_burdens_and_payroll_inclusion():
    company_id = 9502

    casual = client.post(
        "/employees",
        headers=_auth_headers(company_id),
        json={"name": "Casual Worker", "labor_class": "CASUAL_LABOUR"},
    )
    assert casual.status_code == 200, casual.text
    casual_body = casual.json()
    assert casual_body["requires_payroll"] is False
    assert casual_body["include_wcb_cost"] is False
    assert casual_body["include_ei_cost"] is False
    assert casual_body["include_tax_cost"] is False

    subcontractor = client.post(
        "/employees",
        headers=_auth_headers(company_id),
        json={"name": "Subcontractor Worker", "labor_class": "SUBCONTRACTOR_HOURLY"},
    )
    assert subcontractor.status_code == 200, subcontractor.text
    subcontractor_body = subcontractor.json()
    assert subcontractor_body["requires_payroll"] is False
    assert subcontractor_body["include_wcb_cost"] is False
    assert subcontractor_body["include_ei_cost"] is False
    assert subcontractor_body["include_tax_cost"] is False

    db = SessionLocal()
    try:
        casual_deductions = compute_deduction_amounts(
            company_id=company_id,
            employee_id=int(casual_body["id"]),
            gross_pay_cents=10000,
            db=db,
            as_of_date=date(2026, 3, 7),
        )
        subcontractor_deductions = compute_deduction_amounts(
            company_id=company_id,
            employee_id=int(subcontractor_body["id"]),
            gross_pay_cents=10000,
            db=db,
            as_of_date=date(2026, 3, 7),
        )
    finally:
        db.close()

    assert casual_deductions == []
    assert subcontractor_deductions == []


def test_payroll_run_generation_excludes_non_payroll_workers():
    company_id = 9503
    pay_period_id = "pp-worker-class-1"
    _seed_pay_period(company_id, pay_period_id)
    job_id, scope_id = _seed_job_scope(company_id, "WC")

    payroll_employee = client.post(
        "/employees",
        headers=_auth_headers(company_id),
        json={"name": "Payroll Employee", "labor_class": "PAYROLL_EMPLOYEE"},
    )
    casual_employee = client.post(
        "/employees",
        headers=_auth_headers(company_id),
        json={"name": "Casual Worker", "labor_class": "CASUAL_LABOUR"},
    )
    subcontractor_employee = client.post(
        "/employees",
        headers=_auth_headers(company_id),
        json={"name": "Subcontractor Worker", "labor_class": "SUBCONTRACTOR_HOURLY"},
    )

    assert payroll_employee.status_code == 200, payroll_employee.text
    assert casual_employee.status_code == 200, casual_employee.text
    assert subcontractor_employee.status_code == 200, subcontractor_employee.text

    payroll_id = int(payroll_employee.json()["id"])
    casual_id = int(casual_employee.json()["id"])
    subcontractor_id = int(subcontractor_employee.json()["id"])

    _seed_approved_time_entry(
        company_id=company_id,
        employee_id=payroll_id,
        job_id=job_id,
        scope_id=scope_id,
        time_entry_id="te-worker-class-payroll",
        hours=2,
    )
    _seed_approved_time_entry(
        company_id=company_id,
        employee_id=casual_id,
        job_id=job_id,
        scope_id=scope_id,
        time_entry_id="te-worker-class-casual",
        hours=2,
    )
    _seed_approved_time_entry(
        company_id=company_id,
        employee_id=subcontractor_id,
        job_id=job_id,
        scope_id=scope_id,
        time_entry_id="te-worker-class-subcontractor",
        hours=2,
    )

    create_run = client.post(
        "/payroll/runs",
        headers=_auth_headers(company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert create_run.status_code == 200, create_run.text
    run_body = create_run.json()
    assert run_body["items_created"] == 1

    run_detail = client.get(
        f"/payroll/runs/{run_body['payroll_run_id']}",
        headers=_auth_headers(company_id),
    )
    assert run_detail.status_code == 200, run_detail.text
    items = run_detail.json()["items"]
    assert len(items) == 1
    assert int(items[0]["employee_id"]) == payroll_id


def test_costing_flags_persist_correctly_and_company_scoping_enforced():
    c1 = 9504
    c2 = 9505

    created = client.post(
        "/employees",
        headers=_auth_headers(c1),
        json={"name": "Scoped Worker"},
    )
    assert created.status_code == 200, created.text
    employee_id = int(created.json()["id"])

    update = client.patch(
        f"/employees/{employee_id}",
        headers=_auth_headers(c1),
        json={
            "labor_class": "CASUAL_LABOUR",
            "include_wcb_cost": True,
            "include_ei_cost": False,
            "include_tax_cost": False,
            "requires_payroll": False,
        },
    )
    assert update.status_code == 200, update.text
    updated = update.json()
    assert updated["labor_class"] == "CASUAL_LABOUR"
    assert updated["include_wcb_cost"] is True
    assert updated["include_ei_cost"] is False
    assert updated["include_tax_cost"] is False
    assert updated["requires_payroll"] is False

    own_get = client.get(f"/employees/{employee_id}", headers=_auth_headers(c1))
    assert own_get.status_code == 200
    assert own_get.json()["include_wcb_cost"] is True

    other_get = client.get(f"/employees/{employee_id}", headers=_auth_headers(c2))
    assert other_get.status_code == 404

    other_patch = client.patch(
        f"/employees/{employee_id}",
        headers=_auth_headers(c2),
        json={"name": "Should Fail"},
    )
    assert other_patch.status_code == 404

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.pay_period import PayPeriod
from app.models.scope import Scope
from app.models.time_entry import TimeEntry

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_payroll_execution_case(
    *,
    company_id: int,
    suffix: str,
    approval_status: str = "approved",
) -> tuple[str, int]:
    today = date.today()
    started_at = datetime.now(timezone.utc) - timedelta(hours=8)
    ended_at = started_at + timedelta(hours=4)

    db = SessionLocal()
    try:
        pay_period = PayPeriod(
            pay_period_id=f"pp-exec-{suffix}",
            company_id=company_id,
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
            status="OPEN",
        )
        db.add(pay_period)

        job = Job(company_id=company_id, name=f"Payroll Exec Job {suffix}", is_active=True)
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Payroll Exec Scope {suffix}", is_active=True)
        db.add(scope)
        db.flush()

        employee = Employee(
            company_id=company_id,
            name=f"Payroll Exec Employee {suffix}",
            legal_name=f"Payroll Exec Employee {suffix}",
            is_active=True,
            requires_payroll=True,
            hourly_rate_cents=3000,
            payment_method="DIRECT_DEPOSIT",
            country="CA",
            province="AB",
            province_of_employment="AB",
            federal_claim_amount=150,
        )
        db.add(employee)
        db.flush()

        db.add(
            TimeEntry(
                time_entry_id=f"te-exec-{suffix}",
                company_id=company_id,
                employee_id=employee.id,
                job_id=job.id,
                scope_id=scope.id,
                started_at=started_at,
                ended_at=ended_at,
                status="completed",
                approval_status=approval_status,
            )
        )
        db.commit()
        return str(pay_period.pay_period_id), int(employee.id)
    finally:
        db.close()


def test_execute_payroll_processing_creates_run_and_readies_pay_employees_dataset():
    company_id = 53101
    pay_period_id, employee_id = _seed_payroll_execution_case(company_id=company_id, suffix="ready")

    resp = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["pay_period_id"] == pay_period_id
    assert body["status"] == "FINALIZED"
    assert body["run_created"] is True
    assert body["items_created"] == 1
    assert body["finalized"] is True
    assert body["paystubs"] == {"generated": 1, "skipped": 0}
    assert body["deductions"] == {"generated": 2, "skipped": 0}
    assert body["pay_employees_ready"] is True

    overview = body["processing_overview"]
    assert overview["run_execution"]["counts"] == {
        "payroll_items": 1,
        "paystubs": 1,
        "payroll_deductions": 2,
    }
    assert overview["run_execution"]["readiness"] == {
        "approved_hours_ready": True,
        "payroll_run_ready": True,
        "paystubs_ready": True,
        "deductions_ready": True,
        "pay_employees_ready": True,
    }
    assert overview["approved_hours_review"]["rows"][0]["employee_id"] == employee_id
    assert overview["pay_employees"]["rows"][0]["gross_pay_cents"] == 12000
    assert overview["pay_employees"]["rows"][0]["deductions_cents"] == 960
    assert overview["pay_employees"]["rows"][0]["net_pay_cents"] == 11040
    assert overview["pay_employees"]["rows"][0]["payment_method"] == "DIRECT_DEPOSIT"
    assert overview["pay_employees"]["total_net_payroll_cents"] == 11040


def test_execute_payroll_processing_is_idempotent_for_existing_run():
    company_id = 53102
    pay_period_id, _employee_id = _seed_payroll_execution_case(company_id=company_id, suffix="idem")

    first = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert first.status_code == 200, first.text
    payroll_run_id = first.json()["payroll_run_id"]

    second = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(company_id),
        json={"payroll_run_id": payroll_run_id},
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["payroll_run_id"] == payroll_run_id
    assert body["run_created"] is False
    assert body["items_created"] == 0
    assert body["finalized"] is False
    assert body["paystubs"] == {"generated": 0, "skipped": 1}
    assert body["deductions"] == {"generated": 0, "skipped": 2}
    assert body["pay_employees_ready"] is True


def test_execute_payroll_processing_blocks_when_pending_completed_entries_exist():
    company_id = 53103
    pay_period_id, _employee_id = _seed_payroll_execution_case(
        company_id=company_id,
        suffix="blocked",
        approval_status="pending",
    )

    resp = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "unapproved_time_entries_exist"
    assert detail["pending_entries_count"] == 1


def test_execute_payroll_processing_enforces_company_scoping():
    company_id = 53104
    other_company_id = 53105
    pay_period_id, _employee_id = _seed_payroll_execution_case(company_id=company_id, suffix="scope")

    resp = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(other_company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "PayPeriod not found"

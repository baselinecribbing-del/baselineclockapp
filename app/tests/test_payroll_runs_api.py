from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.models.scope import Scope
from app.models.time_entry import TimeEntry


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _auth_headers(company_id: int) -> dict[str, str]:
    client = TestClient(app)
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def test_list_payroll_runs_scoped_and_filtered():
    company_id = 1
    other_company_id = 2

    db = SessionLocal()
    try:
        db.add_all(
            [
                PayPeriod(
                    pay_period_id="pp-list-1",
                    company_id=company_id,
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 8),
                    status="POSTED",
                ),
                PayPeriod(
                    pay_period_id="pp-list-2",
                    company_id=company_id,
                    start_date=date(2026, 1, 9),
                    end_date=date(2026, 1, 16),
                    status="POSTED",
                ),
                PayPeriod(
                    pay_period_id="pp-list-3",
                    company_id=company_id,
                    start_date=date(2026, 1, 17),
                    end_date=date(2026, 1, 24),
                    status="POSTED",
                ),
                PayPeriod(
                    pay_period_id="pp-list-other",
                    company_id=other_company_id,
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 8),
                    status="POSTED",
                ),
            ]
        )
        db.flush()

        db.add_all(
            [
                PayrollRun(
                    payroll_run_id="pr-list-posted-newer",
                    company_id=company_id,
                    pay_period_id="pp-list-2",
                    status="POSTED",
                    posted_at=datetime(2026, 1, 16, 12, 0, 0),
                ),
                PayrollRun(
                    payroll_run_id="pr-list-draft",
                    company_id=company_id,
                    pay_period_id="pp-list-3",
                    status="DRAFT",
                    posted_at=None,
                ),
                PayrollRun(
                    payroll_run_id="pr-list-posted-older",
                    company_id=company_id,
                    pay_period_id="pp-list-1",
                    status="POSTED",
                    posted_at=datetime(2026, 1, 8, 12, 0, 0),
                ),
                PayrollRun(
                    payroll_run_id="pr-list-other-company",
                    company_id=other_company_id,
                    pay_period_id="pp-list-other",
                    status="POSTED",
                    posted_at=datetime(2026, 1, 8, 12, 0, 0),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    headers = _auth_headers(company_id)

    r = client.get("/payroll/runs", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    ids = [row["payroll_run_id"] for row in body["rows"]]
    assert ids == [
        "pr-list-posted-newer",
        "pr-list-posted-older",
        "pr-list-draft",
    ]

    r2 = client.get("/payroll/runs?status=POSTED", headers=headers)
    assert r2.status_code == 200, r2.text
    ids2 = [row["payroll_run_id"] for row in r2.json()["rows"]]
    assert ids2 == ["pr-list-posted-newer", "pr-list-posted-older"]

    r3 = client.get("/payroll/runs?pay_period_id=pp-list-1", headers=headers)
    assert r3.status_code == 200, r3.text
    ids3 = [row["payroll_run_id"] for row in r3.json()["rows"]]
    assert ids3 == ["pr-list-posted-older"]

    r4 = client.get("/payroll/runs?pay_period_id=pp-list-3", headers=headers)
    assert r4.status_code == 200, r4.text
    ids4 = [row["payroll_run_id"] for row in r4.json()["rows"]]
    assert ids4 == ["pr-list-draft"]


def test_get_payroll_run_detail_returns_items_and_total():
    company_id = 1
    payroll_run_id = "pr-detail-1"
    pay_period_id = "pp-detail-1"

    db = SessionLocal()
    try:
        employee_1 = Employee(company_id=company_id, name="Payroll Detail Employee 1")
        employee_2 = Employee(company_id=company_id, name="Payroll Detail Employee 2")
        db.add_all([employee_1, employee_2])
        db.flush()

        db.add(
            PayPeriod(
                pay_period_id=pay_period_id,
                company_id=company_id,
                start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 8),
                status="POSTED",
            )
        )
        db.flush()

        db.add(
            PayrollRun(
                payroll_run_id=payroll_run_id,
                company_id=company_id,
                pay_period_id=pay_period_id,
                status="POSTED",
                posted_at=_utcnow(),
            )
        )
        db.flush()

        db.add_all(
            [
                PayrollItem(
                    company_id=company_id,
                    payroll_run_id=payroll_run_id,
                    employee_id=employee_1.id,
                    hours=1.5,
                    rate_cents=2500,
                    gross_pay_cents=3750,
                    meta={"job_id": 11},
                ),
                PayrollItem(
                    company_id=company_id,
                    payroll_run_id=payroll_run_id,
                    employee_id=employee_2.id,
                    hours=2,
                    rate_cents=3000,
                    gross_pay_cents=6000,
                    meta={"job_id": 12},
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    headers = _auth_headers(company_id)

    r = client.get(f"/payroll/runs/{payroll_run_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["payroll_run"]["payroll_run_id"] == payroll_run_id
    assert body["gross_total_cents"] == 9750
    assert len(body["items"]) == 2
    assert [item["gross_pay_cents"] for item in body["items"]] == [3750, 6000]
    assert body["items"][0]["hours"] == "1.50"
    assert body["items"][1]["hours"] == "2.00"

    missing = client.get("/payroll/runs/does-not-exist", headers=headers)
    assert missing.status_code == 404, missing.text
    assert missing.json()["detail"] == "Not found"


def test_create_payroll_run_generates_items_from_approved_time_entries():
    company_id = 1
    pay_period_id = "pp-generate-1"
    start_day = date(2026, 3, 1)
    end_day = date(2026, 3, 14)

    db = SessionLocal()
    try:
        approved_employee = Employee(company_id=company_id, name="Approved Emp", hourly_rate_cents=3000)
        pending_employee = Employee(company_id=company_id, name="Pending Emp", hourly_rate_cents=3200)
        db.add_all([approved_employee, pending_employee])
        db.flush()

        approved_job = Job(company_id=company_id, name="Approved Job", is_active=True)
        pending_job = Job(company_id=company_id, name="Pending Job", is_active=True)
        db.add_all([approved_job, pending_job])
        db.flush()

        approved_scope = Scope(company_id=company_id, name="Approved Scope", is_active=True, job_id=approved_job.id)
        pending_scope = Scope(company_id=company_id, name="Pending Scope", is_active=True, job_id=pending_job.id)
        db.add_all([approved_scope, pending_scope])
        db.flush()

        db.add(
            PayPeriod(
                pay_period_id=pay_period_id,
                company_id=company_id,
                start_date=start_day,
                end_date=end_day,
                status="POSTED",
            )
        )
        db.flush()

        approved_start = datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)
        approved_end = approved_start + timedelta(hours=2)
        pending_start = datetime(2026, 3, 4, 9, 0, 0, tzinfo=timezone.utc)
        pending_end = pending_start + timedelta(hours=3)

        db.add_all(
            [
                TimeEntry(
                    time_entry_id="te-approved-payroll-1",
                    company_id=company_id,
                    employee_id=approved_employee.id,
                    job_id=approved_job.id,
                    scope_id=approved_scope.id,
                    started_at=approved_start,
                    ended_at=approved_end,
                    status="completed",
                    approval_status="approved",
                ),
                TimeEntry(
                    time_entry_id="te-pending-payroll-1",
                    company_id=company_id,
                    employee_id=pending_employee.id,
                    job_id=pending_job.id,
                    scope_id=pending_scope.id,
                    started_at=pending_start,
                    ended_at=pending_end,
                    status="completed",
                    approval_status="pending",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    headers = _auth_headers(company_id)

    created = client.post(
        "/payroll/runs",
        json={"pay_period_id": pay_period_id},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["company_id"] == company_id
    assert payload["pay_period_id"] == pay_period_id
    assert payload["status"] == "DRAFT"
    assert payload["items_created"] == 1

    payroll_run_id = payload["payroll_run_id"]
    detail = client.get(f"/payroll/runs/{payroll_run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["gross_total_cents"] == 6000
    assert len(body["items"]) == 1
    assert body["items"][0]["hours"] == "2.00"
    assert body["items"][0]["rate_cents"] == 3000
    assert body["items"][0]["gross_pay_cents"] == 6000
    assert body["items"][0]["meta"]["time_entry_id"] == "te-approved-payroll-1"


def test_create_payroll_run_requires_company_scoped_pay_period():
    company_id = 1
    other_company_id = 2

    db = SessionLocal()
    try:
        db.add(
            PayPeriod(
                pay_period_id="pp-other-company-only",
                company_id=other_company_id,
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 14),
                status="POSTED",
            )
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    headers = _auth_headers(company_id)

    created = client.post(
        "/payroll/runs",
        json={"pay_period_id": "pp-other-company-only"},
        headers=headers,
    )
    assert created.status_code == 404, created.text
    assert created.json()["detail"] == "PayPeriod not found"

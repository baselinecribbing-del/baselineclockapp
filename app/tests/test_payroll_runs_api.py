from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun


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
                    pay_period_id="pp-list-1",
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
    assert ids3 == ["pr-list-posted-older", "pr-list-draft"]


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

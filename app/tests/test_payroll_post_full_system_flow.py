from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app

from app.models.employee import Employee
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun

from app.services.outbox_processor import process_outbox_batch


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def test_payroll_post_full_system_flow():
    company_id = 1
    payroll_run_id = "pr-e2e-post-full-1"
    pay_period_id = "pp-e2e-post-full-1"

    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name="E2E Job")
        db.add(job)
        db.flush()

        employee = Employee(company_id=company_id, name="E2E Employee")
        db.add(employee)
        db.flush()

        pp = PayPeriod(
            pay_period_id=pay_period_id,
            company_id=company_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 8),
            status="POSTED",
        )
        db.add(pp)
        db.flush()

        pr = PayrollRun(
            payroll_run_id=payroll_run_id,
            company_id=company_id,
            pay_period_id=pay_period_id,
            status="DRAFT",
            posted_at=None,
        )
        db.add(pr)
        db.flush()

        db.add(
            PayrollItem(
                company_id=company_id,
                payroll_run_id=payroll_run_id,
                employee_id=employee.id,
                hours=1,
                rate_cents=30000,
                gross_pay_cents=30000,
                meta={"job_id": job.id},
            )
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)

    # Auth: mint a token for protected endpoints
    tr = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert tr.status_code == 200, tr.text
    tjson = tr.json()
    token = tjson.get("access_token") or tjson.get("token")
    assert token, f"token missing in response: {tjson}"
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }

    # Producer: post payroll run -> enqueues PAYROLL_RUN_POSTED
    r = client.post(f"/payroll/runs/{payroll_run_id}/post", headers=auth_headers)
    assert r.status_code == 200, r.text

    # Consumer: process outbox -> writes ledger rows
    db2 = SessionLocal()
    try:
        idem = f"PAYROLL_RUN_POSTED:{company_id}:{payroll_run_id}"
        outbox_row = (
            db2.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.idempotency_key == idem)
            .one_or_none()
        )
        assert outbox_row is not None

        now = outbox_row.created_at + timedelta(seconds=1)

        result = process_outbox_batch(db=db2, now=now, batch_size=10, max_retries=10)
        db2.commit()
        assert result.processed >= 1
        assert result.failed == 0

        rows = (
            db2.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like(f"{payroll_run_id}:%"))
            .all()
        )
        assert len(rows) >= 1
    finally:
        db2.close()

    # Reconciliation endpoint should now balance
    rr = client.get(f"/payroll/runs/{payroll_run_id}/reconciliation", headers=auth_headers)
    assert rr.status_code == 200, rr.text
    body = rr.json()
    assert body.get("ok") is True

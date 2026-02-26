from datetime import date, datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.services.outbox_processor import process_outbox_batch


def test_payroll_run_posted_is_idempotent():
    db = SessionLocal()
    try:
        company_id = 1

        job = Job(company_id=company_id, name="Idempotent Job")
        db.add(job)
        db.flush()

        employee = Employee(company_id=company_id, name="Idempotent Employee")
        db.add(employee)
        db.flush()

        pay_period = PayPeriod(
            pay_period_id="pp-idem-1",
            company_id=company_id,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 8),
            status="POSTED",
        )
        db.add(pay_period)
        db.flush()

        payroll_run = PayrollRun(
            payroll_run_id="pr-idem-1",
            company_id=company_id,
            pay_period_id=pay_period.pay_period_id,
            status="POSTED",
            posted_at=datetime.now(timezone.utc),
        )
        db.add(payroll_run)
        db.flush()

        payroll_item = PayrollItem(
            company_id=company_id,
            payroll_run_id=payroll_run.payroll_run_id,
            employee_id=employee.id,
            hours=8,
            rate_cents=3000,
            gross_pay_cents=24000,
            meta={"job_id": job.id},
        )
        db.add(payroll_item)
        db.flush()

        outbox_row = EventOutbox(
            company_id=company_id,
            event_type="PAYROLL_RUN_POSTED",
            idempotency_key="idem-payroll-run-1",
            payload={"payroll_run_id": payroll_run.payroll_run_id},
            processed=False,
            retry_count=0,
        )
        db.add(outbox_row)
        db.commit()
        db.refresh(outbox_row)

        now = outbox_row.created_at + timedelta(seconds=1)

        # First pass
        r1 = process_outbox_batch(db=db, now=now, batch_size=10, max_retries=10)
        db.commit()
        assert r1.processed == 1
        assert r1.failed == 0

        ledger_rows_1 = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.job_id == job.id)
            .filter(JobCostLedger.employee_id == employee.id)
            .filter(JobCostLedger.total_cost_cents == 24000)
            .all()
        )
        assert len(ledger_rows_1) == 1

        # Second pass (replay) — should not create duplicates
        r2 = process_outbox_batch(db=db, now=now + timedelta(seconds=5), batch_size=10, max_retries=10)
        db.commit()
        assert r2.processed == 0
        assert r2.failed == 0

        ledger_rows_2 = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.job_id == job.id)
            .filter(JobCostLedger.employee_id == employee.id)
            .filter(JobCostLedger.total_cost_cents == 24000)
            .all()
        )
        assert len(ledger_rows_2) == 1

    finally:
        db.close()

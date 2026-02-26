from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.services.outbox_handlers import handle_payroll_run_posted
from app.services.outbox_processor import process_outbox_batch


def test_payroll_run_posted_failure_increments_retry_and_succeeds_on_retry():
    db = SessionLocal()
    try:
        company_id = 1

        job = Job(company_id=company_id, name="FailRetry Job")
        db.add(job)
        db.flush()

        employee = Employee(company_id=company_id, name="FailRetry Employee")
        db.add(employee)
        db.flush()

        pay_period = PayPeriod(
            pay_period_id="pp-failretry-1",
            company_id=company_id,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 8),
            status="POSTED",
        )
        db.add(pay_period)
        db.flush()

        payroll_run = PayrollRun(
            payroll_run_id="pr-failretry-1",
            company_id=company_id,
            pay_period_id=pay_period.pay_period_id,
            status="POSTED",
            posted_at=datetime.now(timezone.utc),
        )
        db.add(payroll_run)
        db.flush()

        item = PayrollItem(
            company_id=company_id,
            payroll_run_id=payroll_run.payroll_run_id,
            employee_id=employee.id,
            hours=8,
            rate_cents=3000,
            gross_pay_cents=24000,
            meta={"job_id": job.id},
        )
        db.add(item)
        db.flush()

        outbox_row = EventOutbox(
            company_id=company_id,
            event_type="PAYROLL_RUN_POSTED",
            idempotency_key="failretry-payroll-run-1",
            payload={"payroll_run_id": payroll_run.payroll_run_id},
            processed=False,
            retry_count=0,
        )
        db.add(outbox_row)
        db.commit()
        db.refresh(outbox_row)

        now = outbox_row.created_at + timedelta(seconds=1)

        # First attempt: inject failure BEFORE any ledger writing.
        def failing_handler(row: EventOutbox, _db: Session) -> None:
            raise RuntimeError("Injected failure before ledger write")

        handlers_fail = {"PAYROLL_RUN_POSTED": failing_handler}

        r1 = process_outbox_batch(db=db, now=now, batch_size=10, max_retries=10, handlers=handlers_fail)
        db.commit()

        assert r1.processed == 0
        assert r1.failed == 1

        db.refresh(outbox_row)
        assert outbox_row.processed is False
        assert int(outbox_row.retry_count) == 1

        # No ledger rows should exist (failure was before posting).
        rows1 = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like(f"{payroll_run.payroll_run_id}:%"))
            .all()
        )
        assert len(rows1) == 0

        # Second attempt: use real handler; should succeed and create exactly one ledger row.
        handlers_ok = {"PAYROLL_RUN_POSTED": handle_payroll_run_posted}

        r2 = process_outbox_batch(db=db, now=now + timedelta(seconds=5), batch_size=10, max_retries=10, handlers=handlers_ok)
        db.commit()

        assert r2.processed == 1
        assert r2.failed == 0

        db.refresh(outbox_row)
        assert outbox_row.processed is True
        assert int(outbox_row.retry_count) == 1  # kept as history

        rows2 = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like(f"{payroll_run.payroll_run_id}:%"))
            .all()
        )
        assert len(rows2) == 1
        assert rows2[0].total_cost_cents == 24000

    finally:
        db.close()

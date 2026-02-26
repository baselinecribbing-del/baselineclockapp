from datetime import date, datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.event_outbox import EventOutbox
from app.models.job_cost_ledger import JobCostLedger
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.services.outbox_processor import process_outbox_batch


def test_payroll_run_posted_skips_item_without_job_id():
    db = SessionLocal()
    try:
        company_id = 1

        employee = Employee(company_id=company_id, name="NoJob Employee")
        db.add(employee)
        db.flush()

        pay_period = PayPeriod(
            pay_period_id="pp-nojob-1",
            company_id=company_id,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 8),
            status="POSTED",
        )
        db.add(pay_period)
        db.flush()

        payroll_run = PayrollRun(
            payroll_run_id="pr-nojob-1",
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
            meta={},  # no job_id
        )
        db.add(payroll_item)
        db.flush()

        outbox_row = EventOutbox(
            company_id=company_id,
            event_type="PAYROLL_RUN_POSTED",
            idempotency_key="nojob-payroll-run-1",
            payload={"payroll_run_id": payroll_run.payroll_run_id},
            processed=False,
            retry_count=0,
        )
        db.add(outbox_row)
        db.commit()
        db.refresh(outbox_row)

        now = outbox_row.created_at + timedelta(seconds=1)
        result = process_outbox_batch(db=db, now=now, batch_size=10, max_retries=10)
        db.commit()

        assert result.processed == 1
        assert result.failed == 0

        db.refresh(outbox_row)
        assert outbox_row.processed is True

        # No ledger rows should be created because job_id is missing.
        rows = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .all()
        )
        assert len(rows) == 0

    finally:
        db.close()

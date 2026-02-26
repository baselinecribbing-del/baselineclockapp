from datetime import date, datetime, timedelta, timezone

import pytest

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.services.outbox_processor import process_outbox_batch


def test_reconciliation_blocks_processing_until_fixed():
    db = SessionLocal()
    try:
        company_id = 1

        job = Job(company_id=company_id, name="Recon Job")
        db.add(job)
        db.flush()

        employee = Employee(company_id=company_id, name="Recon Employee")
        db.add(employee)
        db.flush()

        pay_period = PayPeriod(
            pay_period_id="pp-recon-1",
            company_id=company_id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 8),
            status="POSTED",
        )
        db.add(pay_period)
        db.flush()

        payroll_run = PayrollRun(
            payroll_run_id="pr-recon-1",
            company_id=company_id,
            pay_period_id=pay_period.pay_period_id,
            status="POSTED",
            posted_at=datetime.now(timezone.utc),
        )
        db.add(payroll_run)
        db.flush()

        # Two items: one has job_id (will post), one missing job_id (will be skipped) => mismatch.
        good_item = PayrollItem(
            company_id=company_id,
            payroll_run_id=payroll_run.payroll_run_id,
            employee_id=employee.id,
            hours=8,
            rate_cents=3000,
            gross_pay_cents=24000,
            meta={"job_id": job.id},
        )
        bad_item = PayrollItem(
            company_id=company_id,
            payroll_run_id=payroll_run.payroll_run_id,
            employee_id=employee.id,
            hours=1,
            rate_cents=3000,
            gross_pay_cents=3000,
            meta={},  # missing job_id => skipped => ledger short
        )
        db.add_all([good_item, bad_item])
        db.flush()

        outbox_row = EventOutbox(
            company_id=company_id,
            event_type="PAYROLL_RUN_POSTED",
            idempotency_key="recon-payroll-run-1",
            payload={"payroll_run_id": payroll_run.payroll_run_id},
            processed=False,
            retry_count=0,
        )
        db.add(outbox_row)
        db.commit()
        db.refresh(outbox_row)

        now = outbox_row.created_at + timedelta(seconds=1)

        # Attempt 1: should fail reconciliation, increment retry_count, and NOT mark processed.
        r1 = process_outbox_batch(db=db, now=now, batch_size=10, max_retries=10)
        db.commit()

        assert r1.processed == 0
        assert r1.failed == 1

        db.refresh(outbox_row)
        assert outbox_row.processed is False
        assert int(outbox_row.retry_count) == 1

        # Ledger has only the good item posted.
        rows1 = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like("pr-recon-1:%"))
            .all()
        )
        assert len(rows1) == 1
        assert rows1[0].total_cost_cents == 24000

        # Fix: attach job_id to the previously-skipped item.
        bad_item.meta = {"job_id": job.id}
        db.add(bad_item)
        db.commit()

        # Attempt 2: should now succeed (idempotent for the first ledger row).
        r2 = process_outbox_batch(db=db, now=now + timedelta(seconds=5), batch_size=10, max_retries=10)
        db.commit()

        assert r2.processed == 1
        assert r2.failed == 0

        db.refresh(outbox_row)
        assert outbox_row.processed is True
        assert int(outbox_row.retry_count) == 1  # retained as history

        rows2 = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like("pr-recon-1:%"))
            .order_by(JobCostLedger.id.asc())
            .all()
        )
        assert len(rows2) == 2
        assert sum(r.total_cost_cents for r in rows2) == 27000

    finally:
        db.close()

import threading
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


def test_outbox_concurrent_workers_do_not_double_post_ledger():
    # Seed data in a single session
    seed_db = SessionLocal()
    try:
        company_id = 1

        job = Job(company_id=company_id, name="Concurrent Job")
        seed_db.add(job)
        seed_db.flush()

        employee = Employee(company_id=company_id, name="Concurrent Employee")
        seed_db.add(employee)
        seed_db.flush()

        pay_period = PayPeriod(
            pay_period_id="pp-concurrent-1",
            company_id=company_id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 8),
            status="POSTED",
        )
        seed_db.add(pay_period)
        seed_db.flush()

        payroll_run = PayrollRun(
            payroll_run_id="pr-concurrent-1",
            company_id=company_id,
            pay_period_id=pay_period.pay_period_id,
            status="POSTED",
            posted_at=datetime.now(timezone.utc),
        )
        seed_db.add(payroll_run)
        seed_db.flush()

        item = PayrollItem(
            company_id=company_id,
            payroll_run_id=payroll_run.payroll_run_id,
            employee_id=employee.id,
            hours=8,
            rate_cents=3000,
            gross_pay_cents=24000,
            meta={"job_id": job.id},
        )
        seed_db.add(item)
        seed_db.flush()

        outbox_row = EventOutbox(
            company_id=company_id,
            event_type="PAYROLL_RUN_POSTED",
            idempotency_key="concurrent-payroll-run-1",
            payload={"payroll_run_id": payroll_run.payroll_run_id},
            processed=False,
            retry_count=0,
        )
        seed_db.add(outbox_row)
        seed_db.commit()
        seed_db.refresh(outbox_row)

        now = outbox_row.created_at + timedelta(seconds=1)

    finally:
        seed_db.close()

    # Two workers, separate DB sessions, start at the same time
    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def worker():
        db = SessionLocal()
        try:
            barrier.wait()
            r = process_outbox_batch(db=db, now=now, batch_size=10, max_retries=10)
            db.commit()
            with lock:
                results.append((r.processed, r.failed))
        finally:
            db.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one worker should have processed the row; the other should see 0 due to SKIP LOCKED.
    processed_total = sum(p for p, _ in results)
    failed_total = sum(f for _, f in results)
    assert processed_total == 1
    assert failed_total == 0

    # Verify final DB state
    verify_db = SessionLocal()
    try:
        outbox = (
            verify_db.query(EventOutbox)
            .filter(EventOutbox.idempotency_key == "concurrent-payroll-run-1")
            .one()
        )
        assert outbox.processed is True

        ledger_rows = (
            verify_db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like("pr-concurrent-1:%"))
            .all()
        )
        assert len(ledger_rows) == 1
        assert ledger_rows[0].total_cost_cents == 24000

    finally:
        verify_db.close()

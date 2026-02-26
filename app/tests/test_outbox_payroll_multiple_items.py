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


def test_payroll_run_posted_creates_one_ledger_row_per_payroll_item():
    db = SessionLocal()
    try:
        company_id = 1

        job_a = Job(company_id=company_id, name="Multi Job A")
        job_b = Job(company_id=company_id, name="Multi Job B")
        db.add_all([job_a, job_b])
        db.flush()

        employee = Employee(company_id=company_id, name="Multi Employee")
        db.add(employee)
        db.flush()

        pay_period = PayPeriod(
            pay_period_id="pp-multi-1",
            company_id=company_id,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 8),
            status="POSTED",
        )
        db.add(pay_period)
        db.flush()

        payroll_run = PayrollRun(
            payroll_run_id="pr-multi-1",
            company_id=company_id,
            pay_period_id=pay_period.pay_period_id,
            status="POSTED",
            posted_at=datetime.now(timezone.utc),
        )
        db.add(payroll_run)
        db.flush()

        item_1 = PayrollItem(
            company_id=company_id,
            payroll_run_id=payroll_run.payroll_run_id,
            employee_id=employee.id,
            hours=8,
            rate_cents=3000,
            gross_pay_cents=24000,
            meta={"job_id": job_a.id},
        )
        item_2 = PayrollItem(
            company_id=company_id,
            payroll_run_id=payroll_run.payroll_run_id,
            employee_id=employee.id,
            hours=4,
            rate_cents=3200,
            gross_pay_cents=12800,
            meta={"job_id": job_b.id},
        )
        db.add_all([item_1, item_2])
        db.flush()

        outbox_row = EventOutbox(
            company_id=company_id,
            event_type="PAYROLL_RUN_POSTED",
            idempotency_key="multi-payroll-run-1",
            payload={"payroll_run_id": payroll_run.payroll_run_id},
            processed=False,
            retry_count=0,
        )
        db.add(outbox_row)
        db.commit()
        db.refresh(outbox_row)

        now = outbox_row.created_at + timedelta(seconds=1)

        r1 = process_outbox_batch(db=db, now=now, batch_size=10, max_retries=10)
        db.commit()
        assert r1.processed == 1
        assert r1.failed == 0

        rows = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.employee_id == employee.id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like(f"{payroll_run.payroll_run_id}:%"))
            .all()
        )
        assert len(rows) == 2

        by_job = {r.job_id: r for r in rows}
        assert by_job[job_a.id].total_cost_cents == 24000
        assert by_job[job_b.id].total_cost_cents == 12800

        # Replay should not create duplicates.
        r2 = process_outbox_batch(db=db, now=now + timedelta(seconds=5), batch_size=10, max_retries=10)
        db.commit()
        assert r2.processed == 0
        assert r2.failed == 0

        rows2 = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.employee_id == employee.id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like(f"{payroll_run.payroll_run_id}:%"))
            .all()
        )
        assert len(rows2) == 2

    finally:
        db.close()

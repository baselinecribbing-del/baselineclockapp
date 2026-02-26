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


def test_payroll_run_posted_ledger_reconciles_to_payroll_items_total():
    db = SessionLocal()
    try:
        company_id = 1

        job_a = Job(company_id=company_id, name="Recon Job A")
        job_b = Job(company_id=company_id, name="Recon Job B")
        db.add_all([job_a, job_b])
        db.flush()

        emp_1 = Employee(company_id=company_id, name="Recon Employee 1")
        emp_2 = Employee(company_id=company_id, name="Recon Employee 2")
        db.add_all([emp_1, emp_2])
        db.flush()

        pay_period = PayPeriod(
            pay_period_id="pp-recon-1",
            company_id=company_id,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 8),
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

        # 3 items across 2 employees and 2 jobs
        items = [
            PayrollItem(
                company_id=company_id,
                payroll_run_id=payroll_run.payroll_run_id,
                employee_id=emp_1.id,
                hours=8,
                rate_cents=3000,
                gross_pay_cents=24000,
                meta={"job_id": job_a.id},
            ),
            PayrollItem(
                company_id=company_id,
                payroll_run_id=payroll_run.payroll_run_id,
                employee_id=emp_1.id,
                hours=2,
                rate_cents=3000,
                gross_pay_cents=6000,
                meta={"job_id": job_b.id},
            ),
            PayrollItem(
                company_id=company_id,
                payroll_run_id=payroll_run.payroll_run_id,
                employee_id=emp_2.id,
                hours=5,
                rate_cents=3200,
                gross_pay_cents=16000,
                meta={"job_id": job_a.id},
            ),
        ]
        db.add_all(items)
        db.flush()

        expected_total = sum(i.gross_pay_cents for i in items)

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
        result = process_outbox_batch(db=db, now=now, batch_size=10, max_retries=10)
        db.commit()

        assert result.processed == 1
        assert result.failed == 0

        rows = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like(f"{payroll_run.payroll_run_id}:%"))
            .all()
        )
        assert len(rows) == 3

        actual_total = sum(r.total_cost_cents for r in rows)
        assert actual_total == expected_total

        # Replay check: totals stable, no duplicates
        result2 = process_outbox_batch(db=db, now=now + timedelta(seconds=5), batch_size=10, max_retries=10)
        db.commit()
        assert result2.processed == 0
        assert result2.failed == 0

        rows2 = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.source_type == "payroll_run_labor")
            .filter(JobCostLedger.cost_category == "labor")
            .filter(JobCostLedger.source_reference_id.like(f"{payroll_run.payroll_run_id}:%"))
            .all()
        )
        assert len(rows2) == 3
        assert sum(r.total_cost_cents for r in rows2) == expected_total

    finally:
        db.close()

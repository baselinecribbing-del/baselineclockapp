from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun


def test_check_constraint_blocks_negative_payroll_item_gross_pay_cents():
    db = SessionLocal()
    try:
        company_id = 1

        job = Job(company_id=company_id, name="CK Job")
        db.add(job)
        db.flush()

        employee = Employee(company_id=company_id, name="CK Employee")
        db.add(employee)
        db.flush()

        pay_period = PayPeriod(
            pay_period_id="pp-ck-1",
            company_id=company_id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            status="POSTED",
        )
        db.add(pay_period)
        db.flush()

        payroll_run = PayrollRun(
            payroll_run_id="pr-ck-1",
            company_id=company_id,
            pay_period_id=pay_period.pay_period_id,
            status="POSTED",
            posted_at=datetime.now(timezone.utc),
        )
        db.add(payroll_run)
        db.flush()

        bad_item = PayrollItem(
            company_id=company_id,
            payroll_run_id=payroll_run.payroll_run_id,
            employee_id=employee.id,
            hours=1,
            rate_cents=100,
            gross_pay_cents=-1,  # should fail ck_payroll_items_gross_pay_cents_nonnegative
            meta={"job_id": job.id},
        )
        db.add(bad_item)

        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    finally:
        db.close()


def test_check_constraint_blocks_negative_job_cost_ledger_total_cost_cents():
    db = SessionLocal()
    try:
        company_id = 1

        bad_ledger = JobCostLedger(
            company_id=company_id,
            job_id=1,
            scope_id=None,
            employee_id=1,
            source_type="payroll_run_labor",
            source_reference_id="ck-ledger:1",
            cost_category="labor",
            quantity="1",
            unit_cost_cents=100,
            total_cost_cents=-1,  # should fail ck_job_cost_ledger_total_cost_cents_nonnegative
            posting_date=datetime.now(timezone.utc),
        )
        db.add(bad_ledger)

        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    finally:
        db.close()

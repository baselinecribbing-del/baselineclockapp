from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.job_cost_ledger import JobCostLedger
from app.services.ledger_reporting_service import job_cost_totals


def test_job_cost_totals_groups_and_sums():
    db = SessionLocal()
    try:
        company_id = 1
        d1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        d2 = datetime(2026, 1, 3, tzinfo=timezone.utc)
        d3 = datetime(2026, 1, 4, tzinfo=timezone.utc)

        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=10,
                    scope_id=None,
                    employee_id=100,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-x:1",
                    cost_category="labor",
                    quantity="8",
                    unit_cost_cents=3000,
                    total_cost_cents=24000,
                    posting_date=d1,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=10,
                    scope_id=None,
                    employee_id=100,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-x:2",
                    cost_category="labor",
                    quantity="2",
                    unit_cost_cents=3000,
                    total_cost_cents=6000,
                    posting_date=d2,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=11,
                    scope_id=None,
                    employee_id=101,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-x:3",
                    cost_category="labor",
                    quantity="5",
                    unit_cost_cents=3200,
                    total_cost_cents=16000,
                    posting_date=d2,
                ),
            ]
        )
        db.commit()

        res = job_cost_totals(
            company_id=company_id,
            date_start=d1,
            date_end=d3,
            db=db,
        )

        groups = res["groups"]
        assert len(groups) == 2

        g0 = groups[0]
        g1 = groups[1]

        assert (g0["job_id"], g0["employee_id"]) == (10, 100)
        assert g0["row_count"] == 2
        assert g0["total_cost_cents"] == 30000

        assert (g1["job_id"], g1["employee_id"]) == (11, 101)
        assert g1["row_count"] == 1
        assert g1["total_cost_cents"] == 16000

    finally:
        db.close()

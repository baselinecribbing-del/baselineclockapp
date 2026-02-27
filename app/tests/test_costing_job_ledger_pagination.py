from datetime import datetime, timezone
from types import SimpleNamespace

from app.database import SessionLocal
from app.models.employee import Employee
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.routers.costing import get_job_ledger


def test_job_ledger_paginates_rows_unit():
    company_id = 1

    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name="Paginate Job")
        db.add(job)
        db.flush()

        employee = Employee(company_id=company_id, name="Paginate Emp")
        db.add(employee)
        db.flush()

        # 5 deterministic rows
        for i in range(5):
            db.add(
                JobCostLedger(
                    company_id=company_id,
                    job_id=job.id,
                    scope_id=None,
                    employee_id=employee.id,
                    source_type="payroll_run_labor",
                    source_reference_id=f"pag:{i}",
                    cost_category="labor",
                    quantity="1",
                    unit_cost_cents=100,
                    total_cost_cents=100,
                    posting_date=datetime.now(timezone.utc),
                )
            )
        db.commit()

        request = SimpleNamespace(state=SimpleNamespace(company_id=company_id))

        body1 = get_job_ledger(job_id=job.id, request=request, scope_id=None, limit=2, offset=0, _role=None)
        assert body1["limit"] == 2
        assert body1["offset"] == 0
        assert len(body1["rows"]) == 2

        body2 = get_job_ledger(job_id=job.id, request=request, scope_id=None, limit=2, offset=2, _role=None)
        assert body2["limit"] == 2
        assert body2["offset"] == 2
        assert len(body2["rows"]) == 2

        body3 = get_job_ledger(job_id=job.id, request=request, scope_id=None, limit=2, offset=4, _role=None)
        assert len(body3["rows"]) == 1

    finally:
        db.close()

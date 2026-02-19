from datetime import datetime

import pytest
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models.job_cost_ledger import JobCostLedger


def test_job_cost_ledger_update_is_blocked():
    db = SessionLocal()
    try:
        row = JobCostLedger(
            company_id=999,
            job_id=999,
            scope_id=None,
            employee_id=None,
            source_type="LABOR",
            source_reference_id=f"immut-test-{datetime.utcnow().isoformat()}",
            cost_category="LABOR_GROSS",
            quantity=None,
            unit_cost_cents=None,
            total_cost_cents=1,
            posting_date=datetime.utcnow(),
            immutable_flag=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        row.cost_category = "MUTATED"
        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()

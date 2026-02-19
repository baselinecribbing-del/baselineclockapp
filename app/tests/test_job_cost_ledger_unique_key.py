from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.job_cost_ledger import JobCostLedger


def test_job_cost_ledger_unique_posting_key_blocks_duplicates():
    db = SessionLocal()
    try:
        ref = f"uniq-{uuid4()}"

        row1 = JobCostLedger(
            company_id=1,
            job_id=1,
            scope_id=None,
            employee_id=None,
            source_type="LABOR",
            source_reference_id=ref,
            cost_category="LABOR_GROSS",
            quantity=None,
            unit_cost_cents=None,
            total_cost_cents=1,
            posting_date=datetime.utcnow(),
            immutable_flag=True,
        )
        db.add(row1)
        db.commit()

        row2 = JobCostLedger(
            company_id=1,
            job_id=1,
            scope_id=None,
            employee_id=None,
            source_type="LABOR",
            source_reference_id=ref,
            cost_category="LABOR_GROSS",
            quantity=None,
            unit_cost_cents=None,
            total_cost_cents=2,
            posting_date=datetime.utcnow(),
            immutable_flag=True,
        )
        db.add(row2)
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()

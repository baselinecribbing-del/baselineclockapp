from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.time_entry import TimeEntry


def test_unique_active_time_entry_prevents_duplicates():
    company_id = 9501
    employee_id = 9601

    db1 = SessionLocal()
    db2 = SessionLocal()

    try:
        row1 = TimeEntry(
            time_entry_id=str(uuid4()),
            company_id=company_id,
            employee_id=employee_id,
            job_id=1,
            scope_id=1,
            started_at=datetime.utcnow(),
            ended_at=None,
            status="active",
        )

        row2 = TimeEntry(
            time_entry_id=str(uuid4()),
            company_id=company_id,
            employee_id=employee_id,
            job_id=2,
            scope_id=2,
            started_at=datetime.utcnow(),
            ended_at=None,
            status="active",
        )

        db1.add(row1)
        db2.add(row2)

        db1.commit()

        with pytest.raises(IntegrityError):
            db2.commit()
    finally:
        db1.rollback()
        db2.rollback()
        db1.close()
        db2.close()

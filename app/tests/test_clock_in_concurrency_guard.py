from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.time_entry import TimeEntry


def test_unique_active_time_entry_prevents_duplicates(employee_factory, job_factory, scope_factory):
    company_id = 9501
    employee = employee_factory(company_id=company_id)
    job1 = job_factory(company_id=company_id)
    scope1 = scope_factory(company_id=company_id, job_id=job1.id)
    job2 = job_factory(company_id=company_id)
    scope2 = scope_factory(company_id=company_id, job_id=job2.id)
    employee_id = employee.id

    db1 = SessionLocal()
    db2 = SessionLocal()

    try:
        row1 = TimeEntry(
            time_entry_id=str(uuid4()),
            company_id=company_id,
            employee_id=employee_id,
            job_id=job1.id,
            scope_id=scope1.id,
            started_at=datetime.utcnow(),
            ended_at=None,
            status="active",
        )

        row2 = TimeEntry(
            time_entry_id=str(uuid4()),
            company_id=company_id,
            employee_id=employee_id,
            job_id=job2.id,
            scope_id=scope2.id,
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

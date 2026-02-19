from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.time_entry import TimeEntry


def _get_active_entry(
    db: Session,
    company_id: int,
    employee_id: int,
) -> Optional[TimeEntry]:
    return (
        db.query(TimeEntry)
        .filter(
            TimeEntry.company_id == company_id,
            TimeEntry.employee_id == employee_id,
            TimeEntry.status == "active",
        )
        .first()
    )


def clock_in(
    company_id: int,
    employee_id: int,
    job_id: int,
    scope_id: int,
    started_at: datetime,
    *,
    db: Optional[Session] = None,
) -> TimeEntry:
    """
    If db is provided, this function will NOT commit/close. Caller owns the transaction.
    If db is None, this function manages its own session + commit.
    """
    owns_db = db is None
    if owns_db:
        db = SessionLocal()

    try:
        active_entry = _get_active_entry(db, company_id, employee_id)
        if active_entry is not None:
            raise ValueError("Active time entry already exists for employee in company")

        time_entry = TimeEntry(
            time_entry_id=str(uuid4()),
            company_id=company_id,
            employee_id=employee_id,
            job_id=job_id,
            scope_id=scope_id,
            started_at=started_at,
            ended_at=None,
            status="active",
        )

        db.add(time_entry)
        db.flush()
        db.refresh(time_entry)

        if owns_db:
            db.commit()

        return time_entry
    except Exception:
        if owns_db:
            db.rollback()
        raise
    finally:
        if owns_db:
            db.close()


def clock_out(
    company_id: int,
    employee_id: int,
    ended_at: datetime,
    *,
    db: Optional[Session] = None,
) -> TimeEntry:
    """
    If db is provided, this function will NOT commit/close. Caller owns the transaction.
    If db is None, this function manages its own session + commit.
    """
    owns_db = db is None
    if owns_db:
        db = SessionLocal()

    try:
        active_entry = _get_active_entry(db, company_id, employee_id)
        if active_entry is None:
            raise ValueError("No active time entry found for employee in company")

        active_entry.ended_at = ended_at
        active_entry.status = "completed"

        db.flush()
        db.refresh(active_entry)

        if owns_db:
            db.commit()

        return active_entry
    except Exception:
        if owns_db:
            db.rollback()
        raise
    finally:
        if owns_db:
            db.close()

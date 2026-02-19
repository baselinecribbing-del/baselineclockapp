from datetime import datetime, timedelta, timezone

import pytest

from app.database import SessionLocal
from app.models.time_entry import TimeEntry
from app.services import time_engine_v10 as time_engine


def _db():
    return SessionLocal()


def _cleanup(company_id: int, employee_id: int):
    db = _db()
    try:
        db.query(TimeEntry).filter(
            TimeEntry.company_id == company_id,
            TimeEntry.employee_id == employee_id,
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _count_active(company_id: int, employee_id: int) -> int:
    db = _db()
    try:
        return (
            db.query(TimeEntry)
            .filter(
                TimeEntry.company_id == company_id,
                TimeEntry.employee_id == employee_id,
                TimeEntry.status == "active",
            )
            .count()
        )
    finally:
        db.close()


def _latest(company_id: int, employee_id: int) -> TimeEntry:
    db = _db()
    try:
        row = (
            db.query(TimeEntry)
            .filter(
                TimeEntry.company_id == company_id,
                TimeEntry.employee_id == employee_id,
            )
            .order_by(TimeEntry.started_at.desc())
            .first()
        )
        assert row is not None
        return row
    finally:
        db.close()


def test_clock_in_creates_active_entry():
    company_id = 61001
    employee_id = 61002
    _cleanup(company_id, employee_id)

    started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    row = time_engine.clock_in(
        company_id=company_id,
        employee_id=employee_id,
        job_id=1,
        scope_id=1,
        started_at=started_at,
    )

    assert row.company_id == company_id
    assert row.employee_id == employee_id
    assert row.status == "active"
    assert _count_active(company_id, employee_id) == 1


def test_clock_in_rejects_when_active_exists():
    company_id = 62001
    employee_id = 62002
    _cleanup(company_id, employee_id)

    started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    time_engine.clock_in(
        company_id=company_id,
        employee_id=employee_id,
        job_id=1,
        scope_id=1,
        started_at=started_at,
    )

    with pytest.raises(ValueError) as exc:
        time_engine.clock_in(
            company_id=company_id,
            employee_id=employee_id,
            job_id=1,
            scope_id=1,
            started_at=datetime.now(timezone.utc),
        )

    assert "Active time entry already exists" in str(exc.value)
    assert _count_active(company_id, employee_id) == 1


def test_clock_out_completes_active_entry():
    company_id = 63001
    employee_id = 63002
    _cleanup(company_id, employee_id)

    started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    time_engine.clock_in(
        company_id=company_id,
        employee_id=employee_id,
        job_id=1,
        scope_id=1,
        started_at=started_at,
    )

    ended_at = datetime.now(timezone.utc)
    row = time_engine.clock_out(
        company_id=company_id,
        employee_id=employee_id,
        ended_at=ended_at,
    )

    assert row.status == "completed"
    assert row.ended_at is not None
    assert _count_active(company_id, employee_id) == 0

    latest = _latest(company_id, employee_id)
    assert latest.status == "completed"


def test_clock_out_rejects_when_no_active_entry():
    company_id = 64001
    employee_id = 64002
    _cleanup(company_id, employee_id)

    with pytest.raises(ValueError) as exc:
        time_engine.clock_out(
            company_id=company_id,
            employee_id=employee_id,
            ended_at=datetime.now(timezone.utc),
        )

    assert "No active time entry found" in str(exc.value)

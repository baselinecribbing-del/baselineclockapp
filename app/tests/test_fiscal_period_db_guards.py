from datetime import date

import pytest
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models.fiscal_period import FiscalPeriod


def _insert_period(*, db, company_id: int, name: str, start: date, end: date) -> FiscalPeriod:
    row = FiscalPeriod(
        company_id=int(company_id),
        name=str(name),
        period_start=start,
        period_end=end,
        status="OPEN",
    )
    db.add(row)
    db.flush()
    return row


def test_db_blocks_overlapping_fiscal_period_insert_for_same_company():
    db = SessionLocal()
    try:
        company_id = 901
        _insert_period(
            db=db,
            company_id=company_id,
            name="2026-Q1",
            start=date(2026, 1, 1),
            end=date(2026, 3, 31),
        )

        db.add(
            FiscalPeriod(
                company_id=company_id,
                name="2026-overlap",
                period_start=date(2026, 3, 15),
                period_end=date(2026, 4, 30),
                status="OPEN",
            )
        )

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_allows_adjacent_fiscal_periods_for_same_company():
    db = SessionLocal()
    try:
        company_id = 902
        _insert_period(
            db=db,
            company_id=company_id,
            name="2026-Q1",
            start=date(2026, 1, 1),
            end=date(2026, 3, 31),
        )
        _insert_period(
            db=db,
            company_id=company_id,
            name="2026-Q2",
            start=date(2026, 4, 1),
            end=date(2026, 6, 30),
        )

        db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_allows_overlapping_fiscal_periods_for_different_companies():
    db = SessionLocal()
    try:
        _insert_period(
            db=db,
            company_id=903,
            name="2026-Q1-c1",
            start=date(2026, 1, 1),
            end=date(2026, 3, 31),
        )
        _insert_period(
            db=db,
            company_id=904,
            name="2026-Q1-c2",
            start=date(2026, 2, 1),
            end=date(2026, 4, 30),
        )

        db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_blocks_update_that_creates_fiscal_period_overlap():
    db = SessionLocal()
    try:
        company_id = 905
        first = _insert_period(
            db=db,
            company_id=company_id,
            name="2026-Q1",
            start=date(2026, 1, 1),
            end=date(2026, 3, 31),
        )
        _insert_period(
            db=db,
            company_id=company_id,
            name="2026-Q2",
            start=date(2026, 4, 1),
            end=date(2026, 6, 30),
        )
        db.commit()

        first.period_end = date(2026, 4, 15)
        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()

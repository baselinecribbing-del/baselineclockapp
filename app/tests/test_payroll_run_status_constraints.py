from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.pay_period import PayPeriod
from app.models.payroll_run import PayrollRun


def _setup_pay_period(db, company_id: int, pay_period_id: str) -> None:
    db.add(
        PayPeriod(
            pay_period_id=pay_period_id,
            company_id=company_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 8),
            status="POSTED",
        )
    )
    db.flush()


def test_payroll_run_status_must_be_valid():
    db = SessionLocal()
    try:
        company_id = 1
        _setup_pay_period(db, company_id, "pp-status-1")

        db.add(
            PayrollRun(
                payroll_run_id="pr-status-1",
                company_id=company_id,
                pay_period_id="pp-status-1",
                status="NOPE",
                posted_at=None,
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_payroll_run_posted_requires_posted_at():
    db = SessionLocal()
    try:
        company_id = 1
        _setup_pay_period(db, company_id, "pp-status-2")

        db.add(
            PayrollRun(
                payroll_run_id="pr-status-2",
                company_id=company_id,
                pay_period_id="pp-status-2",
                status="POSTED",
                posted_at=None,  # must fail
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_payroll_run_draft_requires_null_posted_at():
    db = SessionLocal()
    try:
        company_id = 1
        _setup_pay_period(db, company_id, "pp-status-3")

        db.add(
            PayrollRun(
                payroll_run_id="pr-status-3",
                company_id=company_id,
                pay_period_id="pp-status-3",
                status="DRAFT",
                posted_at=datetime.now(timezone.utc),  # must fail
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()

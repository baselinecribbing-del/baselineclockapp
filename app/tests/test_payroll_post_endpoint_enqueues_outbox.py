from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.event_outbox import EventOutbox
from app.models.pay_period import PayPeriod
from app.models.payroll_run import PayrollRun


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def test_payroll_post_endpoint_enqueues_outbox():
    payroll_run_id = "pr-e2e-post-1"
    company_id = 1
    pay_period_id = "pp-e2e-post-1"

    # Arrange: create minimal payroll_run + pay_period satisfying constraints.
    db = SessionLocal()
    try:
        db.add(
            PayPeriod(
                pay_period_id=pay_period_id,
                company_id=company_id,
                start_date=datetime(2026, 1, 1).date(),
                end_date=datetime(2026, 1, 8).date(),
                status="POSTED",
            )
        )
        db.add(
            PayrollRun(
                payroll_run_id=payroll_run_id,
                company_id=company_id,
                pay_period_id=pay_period_id,
                status="POSTED",
                posted_at=_utcnow(),
            )
        )
        db.commit()

        # Ensure no outbox row exists yet
        idem = f"PAYROLL_RUN_POSTED:{company_id}:{payroll_run_id}"
        existing = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.idempotency_key == idem)
            .one_or_none()
        )
        assert existing is None
    finally:
        db.close()

    # Act: call endpoint (should be idempotent and enqueue outbox)
    client = TestClient(app)
    r = client.post(f"/payroll/runs/{payroll_run_id}/post")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("status") == "POSTED"

    # Assert: outbox row exists
    db2 = SessionLocal()
    try:
        row = (
            db2.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.idempotency_key == idem)
            .one_or_none()
        )
        assert row is not None
        assert row.event_type == "PAYROLL_RUN_POSTED"
    finally:
        db2.close()

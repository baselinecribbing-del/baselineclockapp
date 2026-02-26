from datetime import timedelta

from app.database import SessionLocal
from app.models.event_outbox import EventOutbox
from app.services.outbox_processor import process_outbox_batch


def test_outbox_payroll_run_posted_dispatches_and_marks_processed(monkeypatch):
    db = SessionLocal()
    calls = []

    def fake_post_labor_costs(*, company_id, payroll_run_id, db):
        # Record the call; do not commit here (keep test deterministic).
        calls.append((company_id, payroll_run_id))
        return {"posted": 0, "skipped": 0, "payroll_run_id": payroll_run_id}

    monkeypatch.setattr(
        "app.services.costing_service.post_labor_costs",
        fake_post_labor_costs,
    )

    try:
        row = EventOutbox(
            company_id=1,
            event_type="PAYROLL_RUN_POSTED",
            idempotency_key="k-payroll-run-posted-1",
            payload={"payroll_run_id": "pr-1"},
            processed=False,
            retry_count=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        now = row.created_at + timedelta(seconds=1)

        result = process_outbox_batch(db=db, now=now, batch_size=10, max_retries=10, handlers=None)
        db.refresh(row)

        assert result.processed == 1
        assert result.failed == 0

        assert row.processed is True
        assert row.processed_at == now

        assert calls == [(1, "pr-1")]

    finally:
        db.close()

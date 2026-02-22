from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.event_outbox import EventOutbox
from app.services.outbox_processor import process_outbox_batch


def test_outbox_retry_increments_and_then_processes():
    db = SessionLocal()
    try:
        # Insert a row that will FAIL first (unknown event_type)
        row = EventOutbox(
            company_id=1,
            event_type="UNKNOWN_EVENT",
            idempotency_key="k-retry-1",
            payload={"x": 1},
            processed=False,
            retry_count=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        # IMPORTANT: 'now' must be >= row.created_at or the worker will deterministically skip it.
        now0 = row.created_at + timedelta(seconds=1)

        # First pass: should fail and increment retry_count (unknown event_type)
        r1 = process_outbox_batch(db=db, now=now0, batch_size=10, max_retries=10, handlers={})
        db.refresh(row)
        assert r1.processed == 0
        assert r1.failed == 1
        assert row.processed is False
        assert row.retry_count == 1

        # Running again at the SAME time should not be due yet:
        # retry_count=1 => backoff 2 seconds, but now0 is only +1s
        r2 = process_outbox_batch(db=db, now=now0, batch_size=10, max_retries=10, handlers={})
        db.refresh(row)
        assert r2.processed == 0
        assert r2.failed == 0
        assert row.retry_count == 1

        # Advance time past backoff (2s for retry_count=1) -> should fail again -> retry_count=2
        now2 = row.created_at + timedelta(seconds=3)
        r3 = process_outbox_batch(db=db, now=now2, batch_size=10, max_retries=10, handlers={})
        db.refresh(row)
        assert r3.processed == 0
        assert r3.failed == 1
        assert row.retry_count == 2

    finally:
        db.rollback()
        db.close()

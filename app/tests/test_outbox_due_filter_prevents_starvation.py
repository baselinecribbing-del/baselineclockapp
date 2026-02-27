from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.event_outbox import EventOutbox
from app.services.outbox_processor import process_outbox_batch


def test_outbox_due_filter_prevents_starvation():
    """
    Regression test:

    If the earliest unprocessed row is NOT due, and batch_size is small,
    we must still process later rows that ARE due.

    Old behavior (bug): LIMIT would grab the not-due row and process 0.
    New behavior: SQL filters due rows before LIMIT so the due row gets processed.
    """
    db = SessionLocal()
    try:
        company_id = 1
        now = datetime.now(timezone.utc)

        # Row 1: not due (retry_count=3 => 8s wait; created "now")
        r1 = EventOutbox(
            company_id=company_id,
            event_type="TIME_ENTRY_CLOCKED_OUT",
            idempotency_key="starve-not-due",
            payload={},
            processed=False,
            retry_count=3,
        )
        db.add(r1)
        db.flush()
        # Force created_at to "now" so it's definitely not due
        r1.created_at = now
        db.flush()

        # Row 2: due (created 10s ago; retry_count=0 => due immediately)
        r2 = EventOutbox(
            company_id=company_id,
            event_type="TIME_ENTRY_CLOCKED_OUT",
            idempotency_key="starve-due",
            payload={},
            processed=False,
            retry_count=0,
        )
        db.add(r2)
        db.flush()
        r2.created_at = now - timedelta(seconds=10)
        db.flush()

        db.commit()

        # Handlers: no-op but must exist
        def _noop(_row, _db):
            return None

        handlers = {"TIME_ENTRY_CLOCKED_OUT": _noop}

        # Critical: batch_size=1, so only one row is eligible to be selected.
        result = process_outbox_batch(db=db, now=now, batch_size=1, max_retries=10, handlers=handlers)
        db.commit()

        assert result.processed == 1
        assert result.failed == 0

        db.refresh(r1)
        db.refresh(r2)

        assert r1.processed is False  # still not due
        assert r2.processed is True   # due row got processed
    finally:
        db.close()

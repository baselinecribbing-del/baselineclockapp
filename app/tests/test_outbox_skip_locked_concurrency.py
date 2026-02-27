from datetime import timedelta, timezone

from app.database import SessionLocal
from app.models.event_outbox import EventOutbox
from app.services.outbox_processor import process_outbox_batch


def test_outbox_skip_locked_prevents_double_processing():
    """
    Two separate DB sessions attempt to process the same row.
    With SKIP LOCKED, only one session should process it.

    Note: process_outbox_batch filters by due rows in SQL, so 'now' must be >= created_at.
    """

    db1 = SessionLocal()
    db2 = SessionLocal()

    try:
        company_id = 1

        row = EventOutbox(
            company_id=company_id,
            event_type="TIME_ENTRY_CLOCKED_OUT",
            idempotency_key="concurrency-test",
            payload={},
            processed=False,
            retry_count=0,
        )
        db1.add(row)
        db1.commit()

        # Ensure row is due under SQL-side due filter: created_at <= now
        db1.refresh(row)
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        now = created_at + timedelta(seconds=1)

        # Simple no-op handler
        def _noop(_row, _db):
            return None

        handlers = {"TIME_ENTRY_CLOCKED_OUT": _noop}

        # First worker grabs the row
        result1 = process_outbox_batch(
            db=db1,
            now=now,
            batch_size=10,
            max_retries=10,
            handlers=handlers,
        )

        # Second worker attempts to grab same row
        result2 = process_outbox_batch(
            db=db2,
            now=now,
            batch_size=10,
            max_retries=10,
            handlers=handlers,
        )

        db1.commit()
        db2.commit()

        assert result1.processed + result2.processed == 1
        assert result1.failed + result2.failed == 0

    finally:
        db1.close()
        db2.close()

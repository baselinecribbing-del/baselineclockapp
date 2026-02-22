from __future__ import annotations

from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.event_outbox import EventOutbox
from app.services.outbox_processor import process_outbox_batch


def _insert_event(db, *, company_id: int, event_type: str, key: str, payload: dict) -> EventOutbox:
    row = EventOutbox(
        company_id=company_id,
        event_type=event_type,
        idempotency_key=key,
        payload=payload,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def test_process_outbox_marks_processed_on_success():
    seed = SessionLocal()
    try:
        _insert_event(
            seed,
            company_id=1,
            event_type="TIME_ENTRY_CLOCKED_OUT",
            key="k1",
            payload={"hello": "world"},
        )
        seed.commit()
    finally:
        seed.close()

    def handler(row: EventOutbox, db):
        assert row.event_type == "TIME_ENTRY_CLOCKED_OUT"
        assert row.payload["hello"] == "world"
        assert row.processed is False

    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        result = process_outbox_batch(
            db=db,
            now=now,
            batch_size=10,
            max_retries=10,
            handlers={"TIME_ENTRY_CLOCKED_OUT": handler},
        )
        db.commit()

        fresh = db.query(EventOutbox).filter(EventOutbox.idempotency_key == "k1").one()
        assert fresh.processed is True
        assert fresh.processed_at is not None
        assert int(fresh.retry_count) == 0
        assert result.processed == 1
        assert result.failed == 0
    finally:
        db.close()


def test_process_outbox_increments_retry_on_failure():
    seed = SessionLocal()
    try:
        _insert_event(
            seed,
            company_id=1,
            event_type="TIME_ENTRY_CLOCKED_OUT",
            key="k2",
            payload={"x": 1},
        )
        seed.commit()
    finally:
        seed.close()

    def handler(_row: EventOutbox, _db):
        raise RuntimeError("boom")

    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        result = process_outbox_batch(
            db=db,
            now=now,
            batch_size=10,
            max_retries=10,
            handlers={"TIME_ENTRY_CLOCKED_OUT": handler},
        )
        db.commit()

        fresh = db.query(EventOutbox).filter(EventOutbox.idempotency_key == "k2").one()
        assert fresh.processed is False
        assert fresh.processed_at is None
        assert int(fresh.retry_count) == 1
        assert result.processed == 0
        assert result.failed == 1
    finally:
        db.close()


def test_process_outbox_uses_skip_locked():
    # Insert one row
    seed = SessionLocal()
    try:
        _insert_event(
            seed,
            company_id=1,
            event_type="TIME_ENTRY_CLOCKED_OUT",
            key="k3",
            payload={"y": 2},
        )
        seed.commit()
    finally:
        seed.close()

    # Session A locks the row (FOR UPDATE) and holds txn open
    a = SessionLocal()
    b = SessionLocal()
    try:
        a.begin()
        _locked = (
            a.query(EventOutbox)
            .filter(EventOutbox.idempotency_key == "k3", EventOutbox.processed.is_(False))
            .with_for_update()
            .one()
        )

        def handler(_row: EventOutbox, _db):
            return

        now = datetime.now(timezone.utc)

        # Session B should skip it due to SKIP LOCKED => processes 0
        b.begin()
        result = process_outbox_batch(
            db=b,
            now=now,
            batch_size=10,
            max_retries=10,
            handlers={"TIME_ENTRY_CLOCKED_OUT": handler},
        )
        b.commit()

        assert result.processed == 0
        assert result.failed == 0

        a.rollback()
    finally:
        b.close()
        a.close()

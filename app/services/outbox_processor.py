import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.event_outbox import EventOutbox

logger = logging.getLogger(__name__)

# Deterministic exponential backoff (no jitter).
# attempt=0 => 0s, attempt=1 => 2s, attempt=2 => 4s, attempt=3 => 8s ... capped.
def _backoff_seconds(attempt: int, *, base: int = 2, cap_seconds: int = 300) -> int:
    if attempt <= 0:
        return 0
    secs = base ** attempt
    return min(secs, cap_seconds)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _due(created_at: datetime, retry_count: int, now: datetime) -> bool:
    # created_at is stored tz-aware (timestamptz). Ensure now is tz-aware.
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    wait = timedelta(seconds=_backoff_seconds(retry_count))
    return now >= (created_at + wait)


@dataclass(frozen=True)
class OutboxProcessResult:
    processed: int
    failed: int


# Event handlers receive the outbox row and a db session.
OutboxHandler = Callable[[EventOutbox, Session], None]


def _default_handlers() -> Dict[str, OutboxHandler]:
    # Import inside the factory to avoid any possibility of circular imports.
    from app.services.outbox_handlers import (
        handle_time_entry_clocked_out,
        handle_payroll_run_posted,
    )

    return {
        "TIME_ENTRY_CLOCKED_OUT": handle_time_entry_clocked_out,
        "PAYROLL_RUN_POSTED": handle_payroll_run_posted,
    }


def process_outbox_batch(
    *,
    db: Optional[Session] = None,
    now: Optional[datetime] = None,
    batch_size: int = 50,
    max_retries: int = 10,
    handlers: Optional[Dict[str, OutboxHandler]] = None,
) -> OutboxProcessResult:
    """
    Deterministically processes up to batch_size pending outbox rows.

    Retry discipline:
      - A row is eligible when now >= created_at + backoff(retry_count)
      - On failure: retry_count increments (capped by max_retries)
      - On success: processed=true, processed_at=now
    """
    owns_db = db is None
    if owns_db:
        db = SessionLocal()

    if now is None:
        now = _utcnow()

    if handlers is None:
        handlers = _default_handlers()

    processed = 0
    failed = 0

    try:
        # Select rows and lock them so we can run multiple workers safely later.
        rows = (
            db.query(EventOutbox)
            .filter(EventOutbox.processed.is_(False))
                        .order_by(EventOutbox.id.asc())
            .with_for_update(skip_locked=True)
            .limit(batch_size)
            .all()
        )

        for row in rows:
            if not _due(row.created_at, row.retry_count, now):
                continue

            handler = handlers.get(row.event_type)
            try:
                if handler is None:
                    raise ValueError(f"Unknown event_type: {row.event_type}")

                handler(row, db)

                row.processed = True
                row.processed_at = now
                db.flush()
                processed += 1
            except Exception:
                row.retry_count = (row.retry_count or 0) + 1

                # Dead-letter (quarantine) after max_retries: mark processed so it won't loop forever.
                if row.retry_count >= max_retries:
                    row.processed = True
                    row.processed_at = now
                    db.flush()
                    failed += 1
                    logger.exception(
                        "Outbox row dead-lettered after max retries",
                        extra={
                            "event_outbox_id": row.id,
                            "event_type": row.event_type,
                            "retry_count": int(row.retry_count),
                            "max_retries": int(max_retries),
                        },
                    )
                else:
                    db.flush()
                    failed += 1
                    logger.exception(
                        "Outbox row processing failed",
                        extra={
                            "event_outbox_id": row.id,
                            "event_type": row.event_type,
                            "retry_count": int(row.retry_count),
                            "max_retries": int(max_retries),
                        },
                    )

        if owns_db:
            db.commit()

        return OutboxProcessResult(processed=processed, failed=failed)
    except Exception:
        if owns_db:
            db.rollback()
        raise
    finally:
        if owns_db:
            db.close()


def try_acquire_outbox_lock(db: Session) -> bool:
    # Two-int advisory lock key. Keep stable forever.
    # Prevents double-processing under uvicorn --reload (two processes).
    res = db.execute(text("select pg_try_advisory_lock(4242, 4243)")).scalar()
    return bool(res)


def release_outbox_lock(db: Session) -> None:
    db.execute(text("select pg_advisory_unlock(4242, 4243)"))

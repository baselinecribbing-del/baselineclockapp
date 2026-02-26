import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.event_outbox import EventOutbox

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboxProcessResult:
    processed: int
    failed: int


# Event handlers receive the outbox row and a db session.
OutboxHandler = Callable[[EventOutbox, Session], None]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _retry_wait(retry_count: int) -> timedelta:
    """Deterministic exponential backoff for outbox retries.

    Contract (as enforced by tests):
      - retry_count <= 0 => due immediately (0s)
      - retry_count == 1 => 2s
      - retry_count == 2 => 4s
      - retry_count == 3 => 8s
      - ... exponential

    Capped at 60s.
    """
    n = int(retry_count) if retry_count is not None else 0
    if n <= 0:
        return timedelta(seconds=0)

    seconds = 2 ** n
    if seconds > 60:
        seconds = 60
    return timedelta(seconds=seconds)


def _due(created_at: datetime, retry_count: int, now: datetime) -> bool:
    """Return True if the outbox row is due for processing.

    Normalizes timezone-naive / timezone-aware mismatches by converting BOTH
    values to UTC-aware before comparing.

    Note: If a datetime is naive, we treat it as UTC.
    """

    def _to_utc_aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    created_at_utc = _to_utc_aware(created_at)
    now_utc = _to_utc_aware(now)

    wait = _retry_wait(retry_count)
    return now_utc >= (created_at_utc + wait)


def _default_handlers() -> Dict[str, OutboxHandler]:
    # Import inside the factory to avoid circular imports.
    from app.services.outbox_handlers import (
        handle_payroll_run_posted,
        handle_time_entry_clocked_out,
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
    """Deterministically process up to `batch_size` pending outbox rows.

    Retry discipline:
      - A row is eligible when now >= created_at + backoff(retry_count)
      - On failure: retry_count increments
      - After retry_count >= max_retries: row is dead-lettered by marking processed=true
      - On success: processed=true, processed_at=now

    Transaction discipline:
      - If a session is passed in, we do NOT commit/rollback it.
      - If we create a session internally, we manage commit/rollback/close.
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
                row.retry_count = int(row.retry_count or 0) + 1

                # Dead-letter after max_retries (inclusive)
                if int(row.retry_count) >= int(max_retries):
                    row.processed = True
                    row.processed_at = now

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
    # Two-int advisory lock key. Keep stable.
    res = db.execute(text("select pg_try_advisory_lock(4242, 4243)")).scalar()
    return bool(res)


def release_outbox_lock(db: Session) -> None:
    db.execute(text("select pg_advisory_unlock(4242, 4243)"))

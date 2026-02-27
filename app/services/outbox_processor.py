import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

from sqlalchemy import case, func, text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.event_outbox import EventOutbox

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboxProcessResult:
    processed: int
    failed: int


OutboxHandler = Callable[[EventOutbox, Session], None]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _retry_wait(retry_count: int) -> timedelta:
    """Deterministic exponential backoff for outbox retries.

    Contract (tests):
      - retry_count <= 0 => 0s
      - retry_count == 1 => 2s
      - retry_count == 2 => 4s
      - retry_count == 3 => 8s
    Capped at 60s.
    """
    n = int(retry_count) if retry_count is not None else 0
    if n <= 0:
        return timedelta(seconds=0)

    seconds = 2**n
    if seconds > 60:
        seconds = 60
    return timedelta(seconds=seconds)


def _due(created_at: datetime, retry_count: int, now: datetime) -> bool:
    """Timezone-normalized due check. Naive datetimes treated as UTC."""

    def _to_utc_aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    created_at_utc = _to_utc_aware(created_at)
    now_utc = _to_utc_aware(now)

    return now_utc >= (created_at_utc + _retry_wait(retry_count))


def _default_handlers() -> Dict[str, OutboxHandler]:
    from app.services.outbox_handlers import (
        handle_payroll_run_posted,
        handle_time_entry_clocked_out,
    )

    return {
        "TIME_ENTRY_CLOCKED_OUT": handle_time_entry_clocked_out,
        "PAYROLL_RUN_POSTED": handle_payroll_run_posted,
    }


def _is_due_clause(now: datetime):
    """
    SQL-side due filter (Postgres).

    Key property: apply due check BEFORE LIMIT so not-due rows don't starve due rows.
    wait_seconds:
      retry_count <= 0 -> 0
      else -> least(60, 2^retry_count)
    due_at := created_at + wait_seconds seconds
    """
    retry_count = func.coalesce(EventOutbox.retry_count, 0)

    wait_seconds = case(
        (retry_count <= 0, 0),
        else_=func.least(60, func.power(2, retry_count)),
    )

    # created_at + (wait_seconds * interval '1 second')
    due_at = EventOutbox.created_at + (wait_seconds * text("interval '1 second'"))
    return due_at <= now


def process_outbox_batch(
    *,
    db: Optional[Session] = None,
    now: Optional[datetime] = None,
    batch_size: int = 50,
    max_retries: int = 10,
    handlers: Optional[Dict[str, OutboxHandler]] = None,
) -> OutboxProcessResult:
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
            .filter(_is_due_clause(now))
            .order_by(EventOutbox.id.asc())
            .with_for_update(skip_locked=True)
            .limit(int(batch_size))
            .all()
        )

        for row in rows:
            # Keep python-side guard as defense-in-depth (should be redundant with SQL filter).
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
    res = db.execute(text("select pg_try_advisory_lock(4242, 4243)")).scalar()
    return bool(res)


def release_outbox_lock(db: Session) -> None:
    db.execute(text("select pg_advisory_unlock(4242, 4243)"))

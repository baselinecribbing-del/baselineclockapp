import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.outbox_processor import (
    process_outbox_batch,
    release_outbox_lock,
    try_acquire_outbox_lock,
)

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def outbox_worker_enabled() -> bool:
    # Disable by default under pytest to keep tests deterministic.
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    v = os.getenv("OUTBOX_WORKER_ENABLED")
    if v is None:
        return True
    return v.strip() not in {"0", "false", "False", "no", "NO"}


async def outbox_worker_loop(*, poll_seconds: float = 1.0, batch_size: int = 50) -> None:
    """
    Single-worker loop. Uses a PG advisory lock so only one process works.
    Deterministic behavior: no jitter, single pass per poll tick.

    IMPORTANT:
      - Advisory locks are connection-scoped, so we keep a dedicated Session open for the lock.
      - Work is done in short-lived transactions that COMMIT each tick so 'processed' updates persist.
    """
    lock_db: Session = SessionLocal()
    have_lock = False
    try:
        have_lock = try_acquire_outbox_lock(lock_db)
        if not have_lock:
            logger.info("Outbox worker did not acquire advisory lock; exiting")
            return

        logger.info("Outbox worker started", extra={"poll_seconds": poll_seconds, "batch_size": batch_size})

        while True:
            now = datetime.now(timezone.utc)

            work_db: Session = SessionLocal()
            try:
                work_db.begin()
                _result = process_outbox_batch(db=work_db, now=now, batch_size=batch_size)
                work_db.commit()
            except Exception:
                work_db.rollback()
                logger.exception("Outbox worker tick failed", extra={"component": "outbox_worker"})
            finally:
                work_db.close()

            await asyncio.sleep(poll_seconds)

    except asyncio.CancelledError:
        logger.info("Outbox worker cancelled; shutting down")
        raise
    except Exception:
        logger.exception("Outbox worker crashed")
        raise
    finally:
        try:
            if have_lock:
                release_outbox_lock(lock_db)
        finally:
            lock_db.close()


def start_outbox_worker_task() -> asyncio.Task | None:
    if not outbox_worker_enabled():
        logger.info("Outbox worker disabled")
        return None

    poll_seconds = float(os.getenv("OUTBOX_POLL_SECONDS", "1.0"))
    batch_size = _env_int("OUTBOX_BATCH_SIZE", 50)
    return asyncio.create_task(outbox_worker_loop(poll_seconds=poll_seconds, batch_size=batch_size))

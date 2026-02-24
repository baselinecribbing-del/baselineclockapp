import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
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
    Single-worker loop.

    Goals:
      - Never crash the server on transient DB failures.
      - Safe under uvicorn --reload (two processes) via PG advisory lock.
      - Recover if Postgres restarts / connections are terminated.
    """
    logger.info(
        "Outbox worker started",
        extra={"poll_seconds": float(poll_seconds), "batch_size": int(batch_size)},
    )

    while True:
        lock_db: Session = SessionLocal()
        have_lock = False

        try:
            # Tag the session so we can terminate ONLY worker connections in Postgres safely.
            try:
                lock_db.execute(text("set application_name = 'frontier_outbox_worker_lock'"))
            except Exception:
                pass

            have_lock = try_acquire_outbox_lock(lock_db)
            if not have_lock:
                try:
                    lock_db.close()
                finally:
                    await asyncio.sleep(poll_seconds)
                continue

            # We hold the advisory lock as long as lock_db connection stays healthy.
            while True:
                work_db: Session = SessionLocal()
                try:
                    try:
                        work_db.execute(text("set application_name = 'frontier_outbox_worker_tick'"))
                    except Exception:
                        pass

                    now = datetime.now(timezone.utc)
                    process_outbox_batch(db=work_db, now=now, batch_size=batch_size)
                    work_db.commit()

                except asyncio.CancelledError:
                    raise

                except (OperationalError, DBAPIError):
                    # Postgres restarted / connection killed.
                    try:
                        work_db.rollback()
                    except Exception:
                        pass

                    # Ensure next tick gets fresh connections.
                    try:
                        engine = work_db.get_bind()
                        if engine is not None and hasattr(engine, "dispose"):
                            engine.dispose()
                    except Exception:
                        pass

                    logger.exception(
                        "Outbox worker tick failed",
                        extra={"component": "outbox_worker", "reason": "dbapi_error"},
                    )
                    await asyncio.sleep(poll_seconds)

                except Exception:
                    try:
                        work_db.rollback()
                    except Exception:
                        pass

                    logger.exception(
                        "Outbox worker tick failed",
                        extra={"component": "outbox_worker", "reason": "unexpected"},
                    )
                    await asyncio.sleep(poll_seconds)

                finally:
                    try:
                        work_db.close()
                    except Exception:
                        pass

                await asyncio.sleep(poll_seconds)

        except asyncio.CancelledError:
            logger.info("Outbox worker cancelled; shutting down")
            raise

        except (OperationalError, DBAPIError):
            # lock connection died; drop pooled conns and restart outer loop.
            logger.exception(
                "Outbox worker lock connection failed",
                extra={"component": "outbox_worker", "reason": "lock_dbapi_error"},
            )
            try:
                engine = lock_db.get_bind()
                if engine is not None and hasattr(engine, "dispose"):
                    engine.dispose()
            except Exception:
                pass
            await asyncio.sleep(poll_seconds)

        except Exception:
            # Do NOT crash the server; log and keep trying.
            logger.exception(
                "Outbox worker crashed",
                extra={"component": "outbox_worker", "reason": "outer_unexpected"},
            )
            await asyncio.sleep(poll_seconds)

        finally:
            try:
                if have_lock:
                    release_outbox_lock(lock_db)
            except Exception:
                pass
            try:
                lock_db.close()
            except Exception:
                pass


def start_outbox_worker_task() -> asyncio.Task | None:
    if not outbox_worker_enabled():
        logger.info("Outbox worker disabled")
        return None

    poll_seconds = float(os.getenv("OUTBOX_POLL_SECONDS", "1.0"))
    batch_size = _env_int("OUTBOX_BATCH_SIZE", 50)
    return asyncio.create_task(outbox_worker_loop(poll_seconds=poll_seconds, batch_size=batch_size))

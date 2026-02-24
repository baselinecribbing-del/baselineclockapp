import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.event_outbox import EventOutbox

logger = logging.getLogger(__name__)


def handle_time_entry_clocked_out(row: EventOutbox, db: Session) -> None:
    """
    TIME_ENTRY_CLOCKED_OUT is emitted on clock_out and currently does NOT include payroll_run_id.
    Keep as a no-op placeholder for future integrations.
    """
    _ = (row, db)
    return


def handle_payroll_run_posted(row: EventOutbox, db: Session) -> None:
    """
    PAYROLL_RUN_POSTED -> post labor costs.
    Expected payload: {"payroll_run_id": "..."}
    """
    payload: Any = row.payload or {}
    payroll_run_id = payload.get("payroll_run_id")

    if not payroll_run_id:
        logger.warning(
            "PAYROLL_RUN_POSTED missing payroll_run_id; skipping costing",
            extra={"event_outbox_id": row.id, "company_id": row.company_id},
        )
        return

    # Import inside handler to avoid circular imports.
    from app.services.costing_service import post_labor_costs

    post_labor_costs(company_id=row.company_id, payroll_run_id=str(payroll_run_id))

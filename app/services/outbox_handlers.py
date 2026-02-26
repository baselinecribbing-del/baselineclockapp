import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.event_outbox import EventOutbox

logger = logging.getLogger(__name__)


def handle_time_entry_clocked_out(row: EventOutbox, db: Session) -> None:
    _ = (row, db)
    return


def handle_payroll_run_posted(row: EventOutbox, db: Session) -> None:
    payload: Any = row.payload or {}

    payroll_run_id: Optional[str] = None
    if isinstance(payload, dict):
        v = payload.get("payroll_run_id") or payload.get("id")
        if v is not None:
            payroll_run_id = str(v)

    if not payroll_run_id:
        logger.info(
            "PAYROLL_RUN_POSTED missing payroll_run_id; skipping",
            extra={"event_outbox_id": row.id},
        )
        return

    from app.services.costing_service import post_labor_costs
    from app.services.reconciliation_service import reconcile_payroll_run_labor

    # Post ledger rows
    post_labor_costs(
        company_id=int(row.company_id),
        payroll_run_id=payroll_run_id,
        db=db,
    )

    # Enforce reconciliation (raises on mismatch)
    reconcile_payroll_run_labor(
        company_id=int(row.company_id),
        payroll_run_id=payroll_run_id,
        db=db,
    )

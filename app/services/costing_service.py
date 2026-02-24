from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.job_cost_ledger import JobCostLedger


def _table_exists(db: Session, table_name: str) -> bool:
    sql = text(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t LIMIT 1"
    )
    return db.execute(sql, {"t": table_name}).first() is not None


def _already_posted(db: Session, company_id: int, source_type: str, source_reference_id: str) -> bool:
    row = (
        db.query(JobCostLedger)
        .filter(
            JobCostLedger.company_id == company_id,
            JobCostLedger.source_type == source_type,
            JobCostLedger.source_reference_id == source_reference_id,
        )
        .first()
    )
    return row is not None


def post_labor_costs(company_id: int, pay_period_id: int) -> Dict[str, Any]:
    """
    Idempotent. HARD FAIL until payroll/remittance snapshot tables exist.
    """
    db = SessionLocal()
    try:
        # Required tables not present in this repo yet
        required = ["remittance_snapshots", "pay_period", "payroll_items", "time_entries"]
        for t in required:
            if not _table_exists(db, t):
                raise ValueError("Payroll tables not present: cannot post labor costs yet")

        # Placeholder: once tables exist, implement allocation + mismatch safeguards
        raise ValueError("Payroll tables not present: cannot post labor costs yet")
    finally:
        db.close()


def post_production_costs(company_id: int, date_start: datetime, date_end: datetime) -> Dict[str, Any]:
    """
    Idempotent. HARD FAIL until production entries + unit cost config exist.
    """
    db = SessionLocal()
    try:
        if not _table_exists(db, "production_entries"):
            raise ValueError("Production entries not present: cannot post production costs yet")
        if not _table_exists(db, "unit_cost_configs"):
            raise ValueError("Unit cost config not present: cannot post production costs yet")

        # Placeholder: once tables exist, implement deterministic unit cost lookup and posting
        raise ValueError("Production entries not present: cannot post production costs yet")
    finally:
        db.close()

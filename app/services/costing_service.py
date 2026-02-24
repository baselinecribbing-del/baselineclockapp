from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.job_cost_ledger import JobCostLedger


def _table_exists(db: Session, table_name: str) -> bool:
    sql = text(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t LIMIT 1"
    )
    return db.execute(sql, {"t": table_name}).first() is not None


def _already_posted(db: Session, company_id: int, source_type: str, source_reference_id: str, cost_category: str) -> bool:
    row = (
        db.query(JobCostLedger)
        .filter(
            JobCostLedger.company_id == company_id,
            JobCostLedger.source_type == source_type,
            JobCostLedger.source_reference_id == source_reference_id,
            JobCostLedger.cost_category == cost_category,
        )
        .first()
    )
    return row is not None


@dataclass(frozen=True)
class _Window:
    start: datetime
    end: datetime  # exclusive


def _dt_range_for_pay_period(start_d: date, end_d: date) -> _Window:
    # Treat pay period end_date as inclusive day; convert to [start 00:00, (end+1) 00:00)
    start_dt = datetime.combine(start_d, time.min)
    end_dt = datetime.combine(end_d + timedelta(days=1), time.min)
    return _Window(start=start_dt, end=end_dt)


def _overlap_seconds(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> int:
    # all datetimes naive in this schema; keep naive comparisons
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return 0
    return int((end - start).total_seconds())


def post_labor_costs(company_id: int, payroll_run_id: str) -> Dict[str, Any]:
    """
    Post labor costs from payroll_items into job_cost_ledger, allocated across
    (job_id, scope_id) using time_entries in the payroll_run's pay_period window.

    Idempotent at the (company_id, source_type, source_reference_id, cost_category) level.
    """
    db = SessionLocal()
    try:
        required = ["pay_period", "payroll_run", "payroll_items", "time_entries", "job_cost_ledger"]
        for t in required:
            if not _table_exists(db, t):
                raise ValueError(f"Missing required table: {t}")

        # Load payroll_run + pay_period window
        run_row = db.execute(
            text(
                """
                SELECT pr.payroll_run_id, pr.company_id, pr.pay_period_id,
                       pp.start_date, pp.end_date
                FROM payroll_run pr
                JOIN pay_period pp ON pp.pay_period_id = pr.pay_period_id
                WHERE pr.payroll_run_id = :rid AND pr.company_id = :cid
                """
            ),
            {"rid": payroll_run_id, "cid": company_id},
        ).mappings().first()

        if not run_row:
            raise ValueError("payroll_run not found for company")

        window = _dt_range_for_pay_period(run_row["start_date"], run_row["end_date"])

        # Pull payroll_items for run
        items = db.execute(
            text(
                """
                SELECT id, employee_id, gross_pay_cents
                FROM payroll_items
                WHERE company_id=:cid AND payroll_run_id=:rid
                ORDER BY employee_id, id
                """
            ),
            {"cid": company_id, "rid": payroll_run_id},
        ).mappings().all()

        if not items:
            return {"posted": 0, "skipped": 0, "reason": "no payroll_items"}

        posted = 0
        skipped = 0

        SOURCE_TYPE = "payroll_run_labor"
        COST_CATEGORY = "labor"

        # group by employee
        by_emp: Dict[int, int] = {}
        for it in items:
            emp_id = int(it["employee_id"])
            by_emp[emp_id] = by_emp.get(emp_id, 0) + int(it["gross_pay_cents"])

        for employee_id, employee_gross_cents in sorted(by_emp.items()):
            # Fetch time entries overlapping pay window (ended only)
            rows = db.execute(
                text(
                    """
                    SELECT job_id, scope_id, started_at, ended_at
                    FROM time_entries
                    WHERE company_id=:cid
                      AND employee_id=:eid
                      AND ended_at IS NOT NULL
                      AND started_at < :wend
                      AND ended_at > :wstart
                    ORDER BY job_id, scope_id, started_at
                    """
                ),
                {"cid": company_id, "eid": employee_id, "wstart": window.start, "wend": window.end},
            ).mappings().all()

            bucket_seconds: Dict[Tuple[int, int], int] = {}
            total_seconds = 0

            for r in rows:
                s = r["started_at"]
                e = r["ended_at"]
                if e is None:
                    continue
                sec = _overlap_seconds(s, e, window.start, window.end)
                if sec <= 0:
                    continue
                key = (int(r["job_id"]), int(r["scope_id"]))
                bucket_seconds[key] = bucket_seconds.get(key, 0) + sec
                total_seconds += sec

            if total_seconds <= 0:
                # Hard fail: you have payroll for employee but no allocatable time.
                raise ValueError(f"No allocatable time_entries for employee_id={employee_id} in pay window")

            # Deterministic allocation: largest remainder method
            # 1) compute exact shares
            allocations: List[Tuple[int, int, int, int]] = []  # (job_id, scope_id, cents_floor, remainder_num)
            cents_assigned = 0

            for (job_id, scope_id), sec in sorted(bucket_seconds.items()):
                # exact = gross * sec / total_seconds
                num = employee_gross_cents * sec
                cents_floor = num // total_seconds
                remainder = num % total_seconds
                allocations.append((job_id, scope_id, int(cents_floor), int(remainder)))
                cents_assigned += int(cents_floor)

            # 2) distribute leftover cents by descending remainder, stable tie-break by key
            leftover = employee_gross_cents - cents_assigned
            if leftover < 0:
                raise ValueError("Allocation error: negative leftover")

            allocations.sort(key=lambda x: (-x[3], x[0], x[1]))
            allocations = [
                (job_id, scope_id, cents_floor + (1 if i < leftover else 0), remainder)
                for i, (job_id, scope_id, cents_floor, remainder) in enumerate(allocations)
            ]

            # 3) write ledger rows
            for job_id, scope_id, cents, _remainder in allocations:
                if cents <= 0:
                    continue

                source_reference_id = f"{payroll_run_id}:{employee_id}:{job_id}:{scope_id}"

                if _already_posted(db, company_id, SOURCE_TYPE, source_reference_id, COST_CATEGORY):
                    skipped += 1
                    continue

                hours = Decimal(bucket_seconds[(job_id, scope_id)]) / Decimal(3600)

                # unit_cost_cents optional; keep deterministic if hours>0
                unit_cost_cents: Optional[int] = None
                if hours > 0:
                    unit_cost_cents = int(Decimal(cents) / hours)

                posting_date = window.end - timedelta(seconds=1)

                db.add(
                    JobCostLedger(
                        company_id=company_id,
                        job_id=job_id,
                        scope_id=scope_id,
                        employee_id=employee_id,
                        source_type=SOURCE_TYPE,
                        source_reference_id=source_reference_id,
                        cost_category=COST_CATEGORY,
                        quantity=hours,
                        unit_cost_cents=unit_cost_cents,
                        total_cost_cents=cents,
                        posting_date=posting_date,
                        immutable_flag=True,
                    )
                )
                posted += 1

        db.commit()
        return {"posted": posted, "skipped": skipped, "payroll_run_id": payroll_run_id}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
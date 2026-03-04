import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.event_outbox import EventOutbox

logger = logging.getLogger(__name__)


def handle_time_entry_clocked_out(row: EventOutbox, db: Session) -> None:
    _ = (row, db)
    return


def handle_time_entry_clocked_in(row: EventOutbox, db: Session) -> None:
    import json
    import os
    import urllib.parse
    import urllib.request

    from app.models.time_entry import TimeEntry

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        # Deterministic tests/CI: no external call if key isn't set.
        return

    payload = row.payload or {}
    lat = payload.get("clock_in_lat")
    lng = payload.get("clock_in_lng")

    if lat is None or lng is None:
        return

    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return

    time_entry_id = payload.get("time_entry_id")
    if not time_entry_id:
        return

    # Idempotent: don't overwrite if already populated
    existing = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.company_id == row.company_id,
            TimeEntry.time_entry_id == str(time_entry_id),
        )
        .first()
    )
    if existing is None:
        return
    if getattr(existing, "clock_in_address", None):
        return

    qs = urllib.parse.urlencode(
        {
            "latlng": f"{lat_f},{lng_f}",
            "key": api_key,
            "result_type": "street_address",
        }
    )
    url = f"https://maps.googleapis.com/maps/api/geocode/json?{qs}"

    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    try:
        data = json.loads(raw)
    except Exception:
        return

    if not isinstance(data, dict):
        return

    status = data.get("status")
    if status != "OK":
        return

    results = data.get("results")
    if not isinstance(results, list) or not results:
        return

    selected = None
    route_fallback = None
    for item in results:
        if not isinstance(item, dict):
            continue
        types = item.get("types")
        if isinstance(types, list):
            if "street_address" in types or "premise" in types:
                selected = item
                break
            if route_fallback is None and "route" in types:
                route_fallback = item

    if selected is None:
        if route_fallback is not None:
            selected = route_fallback
        else:
            first = results[0]
            if not isinstance(first, dict):
                return
            selected = first

    formatted = selected.get("formatted_address")
    if not isinstance(formatted, str) or not formatted.strip():
        return

    existing.clock_in_address = formatted.strip()
    existing.clock_in_address_source = "google"
    db.flush()


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

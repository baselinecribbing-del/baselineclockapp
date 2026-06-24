from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.bin_service_ticket import BinServiceTicket
from app.models.customer_site import CustomerSite
from app.models.waste_bin import WasteBin

_ACTIVE_TICKET_STATUSES = {"OPEN", "SCHEDULED"}

_ALLOWED_TRANSITIONS = {
    "AVAILABLE": {"ON_SITE", "IN_TRANSIT", "OUT_OF_SERVICE"},
    "ON_SITE": {"IN_TRANSIT", "OUT_OF_SERVICE"},
    "IN_TRANSIT": {"ON_SITE", "AT_LANDFILL", "AVAILABLE", "OUT_OF_SERVICE"},
    "AT_LANDFILL": {"AVAILABLE", "OUT_OF_SERVICE"},
    "OUT_OF_SERVICE": {"AVAILABLE"},
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_site_belongs_to_company(*, db: Session, company_id: int, current_site_id: str | None) -> None:
    if current_site_id is None:
        return
    site = (
        db.query(CustomerSite)
        .filter(CustomerSite.company_id == int(company_id))
        .filter(CustomerSite.customer_site_id == str(current_site_id))
        .one_or_none()
    )
    if site is None:
        raise ValueError("Customer site not found")


def ensure_ticket_assignable(*, db: Session, company_id: int, ticket_id: str | None) -> BinServiceTicket | None:
    if ticket_id is None:
        return None

    ticket = (
        db.query(BinServiceTicket)
        .filter(BinServiceTicket.company_id == int(company_id))
        .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
        .one_or_none()
    )
    if ticket is None:
        raise ValueError("Service ticket not found")
    if str(ticket.status) not in _ACTIVE_TICKET_STATUSES:
        raise ValueError("Service ticket is not active")
    return ticket


def validate_status_transition(*, from_status: str, to_status: str) -> None:
    f = str(from_status)
    t = str(to_status)
    if f == t:
        return
    allowed = _ALLOWED_TRANSITIONS.get(f, set())
    if t not in allowed:
        raise ValueError(f"Invalid status transition: {f} -> {t}")


def assign_ticket_to_bin(
    *,
    db: Session,
    company_id: int,
    waste_bin: WasteBin,
    new_ticket_id: str | None,
) -> None:
    current_ticket_id = None if waste_bin.current_ticket_id is None else str(waste_bin.current_ticket_id)
    if new_ticket_id is None or current_ticket_id == str(new_ticket_id):
        waste_bin.current_ticket_id = new_ticket_id
        return

    current_ticket = (
        db.query(BinServiceTicket)
        .filter(BinServiceTicket.company_id == int(company_id))
        .filter(BinServiceTicket.bin_service_ticket_id == str(current_ticket_id))
        .one_or_none()
    )
    if current_ticket is not None and str(current_ticket.status) in _ACTIVE_TICKET_STATUSES:
        raise ValueError("Bin is already assigned to an active ticket")

    waste_bin.current_ticket_id = str(new_ticket_id)


def apply_ticket_completion_to_assigned_bins(*, db: Session, company_id: int, ticket: BinServiceTicket) -> None:
    rows = (
        db.query(WasteBin)
        .filter(WasteBin.company_id == int(company_id))
        .filter(WasteBin.current_ticket_id == str(ticket.bin_service_ticket_id))
        .all()
    )

    if not rows:
        return

    completed_at = ticket.completed_at or _utcnow()
    ticket_type = str(ticket.service_type)

    for row in rows:
        if ticket_type in {"DROP", "DROP_BIN"}:
            row.status = "ON_SITE"
            row.current_site_id = str(ticket.customer_site_id)
        elif ticket_type in {"SWAP", "SWAP_BIN"}:
            if str(row.status) == "ON_SITE":
                row.status = "IN_TRANSIT"
                row.current_site_id = None
            else:
                row.status = "ON_SITE"
                row.current_site_id = str(ticket.customer_site_id)
        elif ticket_type in {"PICKUP", "PICKUP_BIN"}:
            row.status = "IN_TRANSIT"
            row.current_site_id = None
        elif ticket_type == "LANDFILL_DUMP":
            row.status = "AVAILABLE"
            row.current_site_id = None

        row.last_service_at = completed_at
        row.current_ticket_id = None

    db.flush()

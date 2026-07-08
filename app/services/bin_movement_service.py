from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.bin_asset import BinAsset
from app.models.bin_movement import BinMovement
from app.models.bin_service_ticket import BinServiceTicket
from app.models.landfill_trip import LandfillTrip

_MOVEMENT_TYPES = {"DROP", "SWAP_OUT", "SWAP_IN", "LANDFILL_DUMP", "RETURN_TO_YARD"}
_LOCATION_TYPES = {"SITE", "LANDFILL", "YARD"}


def _as_location_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _ensure_bin_exists(*, db: Session, company_id: int, bin_id: str) -> None:
    row = (
        db.query(BinAsset)
        .filter(BinAsset.company_id == int(company_id))
        .filter(BinAsset.bin_asset_id == str(bin_id))
        .one_or_none()
    )
    if row is None:
        raise ValueError("Bin asset not found")


def _ensure_ticket_exists(*, db: Session, company_id: int, ticket_id: str | None) -> None:
    if ticket_id is None:
        return
    row = (
        db.query(BinServiceTicket)
        .filter(BinServiceTicket.company_id == int(company_id))
        .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
        .one_or_none()
    )
    if row is None:
        raise ValueError("Service ticket not found")


def _ensure_landfill_trip_exists(*, db: Session, company_id: int, landfill_trip_id: str | None) -> None:
    if landfill_trip_id is None:
        return
    row = (
        db.query(LandfillTrip)
        .filter(LandfillTrip.company_id == int(company_id))
        .filter(LandfillTrip.landfill_trip_id == str(landfill_trip_id))
        .one_or_none()
    )
    if row is None:
        raise ValueError("Landfill trip not found")


def _record(
    *,
    db: Session,
    company_id: int,
    bin_id: str,
    movement_type: str,
    from_location_type: str,
    from_location_id: str | None,
    to_location_type: str,
    to_location_id: str | None,
    related_ticket_id: str | None = None,
    related_landfill_trip_id: str | None = None,
    created_at: datetime | None = None,
) -> BinMovement:
    if str(movement_type) not in _MOVEMENT_TYPES:
        raise ValueError("Invalid movement type")
    if str(from_location_type) not in _LOCATION_TYPES:
        raise ValueError("Invalid from location type")
    if str(to_location_type) not in _LOCATION_TYPES:
        raise ValueError("Invalid to location type")

    _ensure_bin_exists(db=db, company_id=company_id, bin_id=bin_id)
    _ensure_ticket_exists(db=db, company_id=company_id, ticket_id=related_ticket_id)
    _ensure_landfill_trip_exists(db=db, company_id=company_id, landfill_trip_id=related_landfill_trip_id)

    row = BinMovement(
        company_id=int(company_id),
        bin_id=str(bin_id),
        movement_type=str(movement_type),
        from_location_type=str(from_location_type),
        from_location_id=_as_location_id(from_location_id),
        to_location_type=str(to_location_type),
        to_location_id=_as_location_id(to_location_id),
        related_ticket_id=None if related_ticket_id is None else str(related_ticket_id),
        related_landfill_trip_id=(
            None if related_landfill_trip_id is None else str(related_landfill_trip_id)
        ),
    )
    if created_at is not None:
        row.created_at = created_at

    db.add(row)
    db.flush()
    return row


def record_drop(
    *,
    db: Session,
    company_id: int,
    bin_id: str,
    customer_site_id: str,
    related_ticket_id: str,
    created_at: datetime | None = None,
) -> BinMovement:
    return _record(
        db=db,
        company_id=company_id,
        bin_id=bin_id,
        movement_type="DROP",
        from_location_type="YARD",
        from_location_id=None,
        to_location_type="SITE",
        to_location_id=customer_site_id,
        related_ticket_id=related_ticket_id,
        created_at=created_at,
    )


def record_swap(
    *,
    db: Session,
    company_id: int,
    bin_id: str,
    customer_site_id: str,
    related_ticket_id: str,
    created_at: datetime | None = None,
) -> tuple[BinMovement, BinMovement]:
    swap_out = _record(
        db=db,
        company_id=company_id,
        bin_id=bin_id,
        movement_type="SWAP_OUT",
        from_location_type="SITE",
        from_location_id=customer_site_id,
        to_location_type="YARD",
        to_location_id=None,
        related_ticket_id=related_ticket_id,
        created_at=created_at,
    )
    swap_in = _record(
        db=db,
        company_id=company_id,
        bin_id=bin_id,
        movement_type="SWAP_IN",
        from_location_type="YARD",
        from_location_id=None,
        to_location_type="SITE",
        to_location_id=customer_site_id,
        related_ticket_id=related_ticket_id,
        created_at=created_at,
    )
    return swap_out, swap_in


def record_dump(
    *,
    db: Session,
    company_id: int,
    bin_id: str,
    dump_site_name: str,
    related_ticket_id: str | None,
    related_landfill_trip_id: str,
    from_site_id: str | None = None,
    created_at: datetime | None = None,
) -> BinMovement:
    return _record(
        db=db,
        company_id=company_id,
        bin_id=bin_id,
        movement_type="LANDFILL_DUMP",
        from_location_type="SITE",
        from_location_id=from_site_id,
        to_location_type="LANDFILL",
        to_location_id=dump_site_name,
        related_ticket_id=related_ticket_id,
        related_landfill_trip_id=related_landfill_trip_id,
        created_at=created_at,
    )


def record_return(
    *,
    db: Session,
    company_id: int,
    bin_id: str,
    from_location_type: str,
    from_location_id: str | None = None,
    related_ticket_id: str | None = None,
    created_at: datetime | None = None,
) -> BinMovement:
    return _record(
        db=db,
        company_id=company_id,
        bin_id=bin_id,
        movement_type="RETURN_TO_YARD",
        from_location_type=from_location_type,
        from_location_id=from_location_id,
        to_location_type="YARD",
        to_location_id=None,
        related_ticket_id=related_ticket_id,
        created_at=created_at,
    )

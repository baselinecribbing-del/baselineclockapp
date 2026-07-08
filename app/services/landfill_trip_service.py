from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.bin_asset import BinAsset
from app.models.bin_service_photo import BinServicePhoto
from app.models.bin_service_ticket import BinServiceTicket
from app.models.job_cost_ledger import JobCostLedger
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.landfill_trip import LandfillTrip
from app.services.bin_movement_service import record_dump


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _configured_cost_per_km_cents() -> int:
    raw = os.getenv("WASTE_BIN_COST_PER_KM_CENTS", "0").strip()
    try:
        parsed = int(raw)
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _to_decimal_km(value: float | int | str | Decimal) -> Decimal:
    try:
        km = Decimal(str(value))
    except Exception as exc:
        raise ValueError("km_driven must be numeric") from exc

    if km < Decimal("0"):
        raise ValueError("km_driven must be nonnegative")
    return km.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def record_landfill_trip(
    *,
    company_id: int,
    bin_service_ticket_id: str,
    bin_asset_id: str,
    dump_site_name: str,
    dump_cost_cents: int,
    km_driven: float | int | str | Decimal,
    receipt_photo_id: str | None,
    db: Session,
) -> LandfillTrip:
    site_name = str(dump_site_name).strip()
    if not site_name:
        raise ValueError("dump_site_name is required")

    if int(dump_cost_cents) < 0:
        raise ValueError("dump_cost_cents must be nonnegative")

    km = _to_decimal_km(km_driven)

    ticket = (
        db.query(BinServiceTicket)
        .filter(BinServiceTicket.company_id == int(company_id))
        .filter(BinServiceTicket.bin_service_ticket_id == str(bin_service_ticket_id))
        .one_or_none()
    )
    if ticket is None:
        raise ValueError("Service ticket not found")

    if str(ticket.status) != "COMPLETED":
        raise ValueError("Service ticket must be COMPLETED before recording landfill trip")

    existing = (
        db.query(LandfillTrip)
        .filter(LandfillTrip.company_id == int(company_id))
        .filter(LandfillTrip.bin_service_ticket_id == str(bin_service_ticket_id))
        .one_or_none()
    )
    if existing is not None:
        raise ValueError("Landfill trip already exists for ticket")

    asset = (
        db.query(BinAsset)
        .filter(BinAsset.company_id == int(company_id))
        .filter(BinAsset.bin_asset_id == str(bin_asset_id))
        .one_or_none()
    )
    if asset is None:
        raise ValueError("Bin asset not found")

    if ticket.job_purchase_order_id is None:
        raise ValueError("Service ticket must be linked to a job purchase order for costing")

    po = (
        db.query(JobPurchaseOrder)
        .filter(JobPurchaseOrder.company_id == int(company_id))
        .filter(JobPurchaseOrder.job_purchase_order_id == str(ticket.job_purchase_order_id))
        .one_or_none()
    )
    if po is None:
        raise ValueError("Job purchase order not found")

    if receipt_photo_id is not None:
        receipt = (
            db.query(BinServicePhoto)
            .filter(BinServicePhoto.company_id == int(company_id))
            .filter(BinServicePhoto.bin_service_photo_id == str(receipt_photo_id))
            .one_or_none()
        )
        if receipt is None:
            raise ValueError("Receipt photo not found")
        if str(receipt.bin_service_ticket_id) != str(bin_service_ticket_id):
            raise ValueError("Receipt photo must belong to the same service ticket")
        if str(receipt.photo_type) != "RECEIPT":
            raise ValueError("receipt_photo_id must reference a RECEIPT photo")

    now = _utcnow()
    trip = LandfillTrip(
        company_id=int(company_id),
        bin_service_ticket_id=str(bin_service_ticket_id),
        bin_asset_id=str(bin_asset_id),
        dump_site_name=site_name,
        receipt_photo_id=None if receipt_photo_id is None else str(receipt_photo_id),
        dump_cost_cents=int(dump_cost_cents),
        km_driven=km,
        completed_at=now,
    )
    db.add(trip)
    db.flush()

    record_dump(
        db=db,
        company_id=int(company_id),
        bin_id=str(bin_asset_id),
        dump_site_name=site_name,
        related_ticket_id=str(bin_service_ticket_id),
        related_landfill_trip_id=str(trip.landfill_trip_id),
        from_site_id=None if ticket.customer_site_id is None else str(ticket.customer_site_id),
        created_at=now,
    )

    dump_ref = f"landfill_trip:{trip.landfill_trip_id}:dump"
    db.add(
        JobCostLedger(
            company_id=int(company_id),
            job_id=int(po.job_id),
            scope_id=None if po.scope_id is None else int(po.scope_id),
            employee_id=None,
            source_type="landfill_trip",
            source_reference_id=dump_ref,
            cost_category="dump_cost",
            quantity=Decimal("1"),
            unit_cost_cents=int(dump_cost_cents),
            total_cost_cents=int(dump_cost_cents),
            job_purchase_order_id=None,
            cost_source="MANUAL",
            posting_date=now,
        )
    )

    km_rate = _configured_cost_per_km_cents()
    km_total = int((km * Decimal(km_rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    km_ref = f"landfill_trip:{trip.landfill_trip_id}:km"
    db.add(
        JobCostLedger(
            company_id=int(company_id),
            job_id=int(po.job_id),
            scope_id=None if po.scope_id is None else int(po.scope_id),
            employee_id=None,
            source_type="landfill_trip",
            source_reference_id=km_ref,
            cost_category="vehicle_km",
            quantity=km,
            unit_cost_cents=int(km_rate),
            total_cost_cents=int(km_total),
            job_purchase_order_id=None,
            cost_source="MANUAL",
            posting_date=now,
        )
    )

    db.flush()
    return trip

from typing import Literal
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.deps.access_control import require_operations_permission
from app.deps.auth import get_actor_user_id, require_auth
from app.deps.entitlements import require_company_module
from app.models.bin_asset import BinAsset
from app.models.bin_movement import BinMovement
from app.models.bin_route_run import BinRouteRun
from app.models.bin_route_run_stop import BinRouteRunStop
from app.models.bin_service_photo import BinServicePhoto
from app.models.bin_service_request import BinServiceRequest
from app.models.bin_service_ticket import BinServiceTicket
from app.models.customer_site import CustomerSite
from app.models.employee import Employee
from app.models.email_ingestion_event import EmailIngestionEvent
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.landfill_trip import LandfillTrip
from app.models.invoice import Invoice
from app.models.invoice_line import InvoiceLine
from app.models.event_outbox import EventOutbox
from app.schemas.waste_bin import (
    BinAssetCreate,
    BinAssetResponse,
    BinRouteRunCreate,
    BinMovementResponse,
    BinRouteRunDetailResponse,
    BinRouteRunPatch,
    BinRouteRunStopResponse,
    BinRouteRunStopSkipCreate,
    BinRouteRunStopsReplace,
    BinRouteRunSummaryResponse,
    BinRouteRunTicketResponse,
    BinReturnToYardCreate,
    BinServicePhotoCreate,
    BinServicePhotoResponse,
    BinServiceRequestFromEmailCreate,
    BinServiceRequestCreate,
    BinServiceRequestResponse,
    BinServiceTicketCompleteCreate,
    BinServiceTicketDispatchCreate,
    BinServiceTicketCreate,
    BinServiceTicketAssignmentPatch,
    BinServiceTicketResponse,
    BinServiceTicketScheduleCreate,
    CustomerSiteCreate,
    CustomerSiteResponse,
    LandfillTripCreate,
    LandfillTripResponse,
    WasteBinNotificationPreviewResponse,
)
from app.services.bin_request_service import create_service_request
from app.services.bin_movement_service import record_drop, record_return, record_swap
from app.services.bin_email_intake_service import create_bin_service_request_from_email
from app.services.invoice_service import generate_invoice_for_completed_ticket
from app.services.landfill_trip_service import record_landfill_trip
from app.services.access_control_service import PrivilegedPermission
from app.services.waste_bin_notifications import (
    render_completion_confirmation,
    render_dispatch_work_order,
    render_request_acknowledgement,
)
from app.services.waste_bin_tracking_service import apply_ticket_completion_to_assigned_bins
from app.schemas.invoice import InvoiceLineResponse, InvoiceResponse

router = APIRouter(prefix="/waste-bin", tags=["Waste Bin"], dependencies=[Depends(require_company_module("waste_bins"))])


def _ensure_company(request: Request, x_company_id: int) -> int:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")
    return int(request.state.company_id)


def _serialize_customer_site(row: CustomerSite) -> CustomerSiteResponse:
    return CustomerSiteResponse(
        customer_site_id=str(row.customer_site_id),
        company_id=int(row.company_id),
        customer_name=str(row.customer_name),
        site_name=row.site_name,
        address_line_1=str(row.address_line_1),
        city=str(row.city),
        province=str(row.province),
        postal_code=str(row.postal_code),
        contact_name=row.contact_name,
        contact_email=row.contact_email,
        contact_phone=row.contact_phone,
        created_at=row.created_at,
    )


def _serialize_asset(row: BinAsset) -> BinAssetResponse:
    return BinAssetResponse(
        bin_asset_id=str(row.bin_asset_id),
        company_id=int(row.company_id),
        bin_number=str(row.bin_number),
        bin_type=str(row.bin_type),
        bin_size=str(row.bin_size),
        status=str(row.status),
        current_customer_site_id=row.current_customer_site_id,
        current_job_purchase_order_id=row.current_job_purchase_order_id,
        created_at=row.created_at,
    )


def _serialize_request(row: BinServiceRequest) -> BinServiceRequestResponse:
    return BinServiceRequestResponse(
        bin_service_request_id=str(row.bin_service_request_id),
        company_id=int(row.company_id),
        customer_site_id=None if row.customer_site_id is None else str(row.customer_site_id),
        job_purchase_order_id=row.job_purchase_order_id,
        source_email_ingestion_event_id=row.source_email_ingestion_event_id,
        request_type=str(row.request_type),
        requested_for=row.requested_for,
        status=str(row.status),
        request_notes=row.request_notes,
        parsed_confidence=None if row.parsed_confidence is None else float(row.parsed_confidence),
        created_at=row.created_at,
    )


def _serialize_ticket(row: BinServiceTicket) -> BinServiceTicketResponse:
    return BinServiceTicketResponse(
        bin_service_ticket_id=str(row.bin_service_ticket_id),
        company_id=int(row.company_id),
        bin_service_request_id=str(row.bin_service_request_id),
        customer_site_id=str(row.customer_site_id),
        job_purchase_order_id=row.job_purchase_order_id,
        assigned_bin_asset_id=row.assigned_bin_asset_id,
        assigned_employee_id=None if row.assigned_employee_id is None else int(row.assigned_employee_id),
        assigned_vehicle_label=row.assigned_vehicle_label,
        service_type=str(row.service_type),
        priority=str(row.priority),
        scheduled_for=row.scheduled_for,
        scheduled_date=row.scheduled_date,
        scheduled_time_window=row.scheduled_time_window,
        status=str(row.status),
        dispatched_at=row.dispatched_at,
        completed_at=row.completed_at,
        completed_by_user_id=row.completed_by_user_id,
        completion_notes=row.completion_notes,
        created_at=row.created_at,
    )


def _ensure_ticket_transition(*, current_status: str, new_status: str) -> None:
    allowed = {
        "OPEN": {"SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"},
        "SCHEDULED": {"DISPATCHED", "COMPLETED", "CANCELLED"},
        "DISPATCHED": {"COMPLETED", "CANCELLED"},
        "COMPLETED": set(),
        "CANCELLED": set(),
    }
    c = str(current_status)
    n = str(new_status)
    if c == n:
        return
    if n not in allowed.get(c, set()):
        raise ValueError(f"Invalid status transition: {c} -> {n}")


def _validate_assignment_refs(
    *,
    db: Session,
    company_id: int,
    assigned_bin_asset_id: str | None,
    assigned_employee_id: int | None,
) -> None:
    if assigned_bin_asset_id is not None:
        asset = (
            db.query(BinAsset)
            .filter(BinAsset.company_id == company_id)
            .filter(BinAsset.bin_asset_id == str(assigned_bin_asset_id))
            .one_or_none()
        )
        if asset is None:
            raise ValueError("Bin asset not found")

    if assigned_employee_id is not None:
        emp = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == int(assigned_employee_id))
            .one_or_none()
        )
        if emp is None:
            raise ValueError("Employee not found")


def _serialize_service_photo(row: BinServicePhoto) -> BinServicePhotoResponse:
    return BinServicePhotoResponse(
        bin_service_photo_id=str(row.bin_service_photo_id),
        company_id=int(row.company_id),
        bin_service_ticket_id=str(row.bin_service_ticket_id),
        photo_type=str(row.photo_type),
        storage_key=str(row.storage_key),
        captured_at=row.captured_at,
        captured_lat=None if row.captured_lat is None else float(row.captured_lat),
        captured_lng=None if row.captured_lng is None else float(row.captured_lng),
        created_at=row.created_at,
    )


def _serialize_landfill_trip(row: LandfillTrip) -> LandfillTripResponse:
    return LandfillTripResponse(
        landfill_trip_id=str(row.landfill_trip_id),
        company_id=int(row.company_id),
        bin_service_ticket_id=str(row.bin_service_ticket_id),
        bin_asset_id=str(row.bin_asset_id),
        dump_site_name=str(row.dump_site_name),
        receipt_photo_id=row.receipt_photo_id,
        dump_cost_cents=int(row.dump_cost_cents),
        km_driven=float(row.km_driven),
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _serialize_movement(row: BinMovement) -> BinMovementResponse:
    return BinMovementResponse(
        id=str(row.id),
        company_id=int(row.company_id),
        bin_id=str(row.bin_id),
        movement_type=str(row.movement_type),
        from_location_type=str(row.from_location_type),
        from_location_id=row.from_location_id,
        to_location_type=str(row.to_location_type),
        to_location_id=row.to_location_id,
        related_ticket_id=row.related_ticket_id,
        related_landfill_trip_id=row.related_landfill_trip_id,
        created_at=row.created_at,
    )


def _serialize_invoice(row: Invoice, lines: list[InvoiceLine]) -> InvoiceResponse:
    return InvoiceResponse(
        invoice_id=str(row.invoice_id),
        company_id=int(row.company_id),
        customer_name=str(row.customer_name),
        customer_site_id=str(row.customer_site_id),
        job_purchase_order_id=row.job_purchase_order_id,
        service_ticket_id=str(row.service_ticket_id),
        invoice_date=row.invoice_date,
        service_date=row.service_date,
        po_number=row.po_number,
        billing_address=str(row.billing_address),
        status=str(row.status),
        subtotal_cents=int(row.subtotal_cents),
        tax_cents=int(row.tax_cents),
        total_cents=int(row.total_cents),
        created_at=row.created_at,
        lines=[
            InvoiceLineResponse(
                invoice_line_id=str(line.invoice_line_id),
                invoice_id=str(line.invoice_id),
                line_type=str(line.line_type),
                description=str(line.description),
                quantity=float(line.quantity),
                unit_price_cents=int(line.unit_price_cents),
                line_total_cents=int(line.line_total_cents),
            )
            for line in lines
        ],
    )


def _build_route_run_summary(*, row: BinRouteRun, stop_rows: list[tuple[BinRouteRunStop, BinServiceTicket]]) -> BinRouteRunSummaryResponse:
    completed_ticket_count = sum(1 for _stop, ticket in stop_rows if str(ticket.status) == "COMPLETED")
    dispatched_ticket_count = sum(1 for _stop, ticket in stop_rows if str(ticket.status) == "DISPATCHED")
    linked_bin_asset_ids = {
        str(stop.bin_asset_id or ticket.assigned_bin_asset_id)
        for stop, ticket in stop_rows
        if stop.bin_asset_id is not None or ticket.assigned_bin_asset_id is not None
    }
    return BinRouteRunSummaryResponse(
        route_run_id=str(row.route_run_id),
        company_id=int(row.company_id),
        route_label=str(row.route_label),
        scheduled_date=row.scheduled_date,
        status=str(row.status),
        assigned_employee_id=None if row.assigned_employee_id is None else int(row.assigned_employee_id),
        notes=row.notes,
        created_at=row.created_at,
        stop_count=len(stop_rows),
        completed_ticket_count=completed_ticket_count,
        dispatched_ticket_count=dispatched_ticket_count,
        assigned_bin_count=len(linked_bin_asset_ids),
    )


def _build_route_run_detail(*, row: BinRouteRun, stop_rows: list[tuple[BinRouteRunStop, BinServiceTicket]]) -> BinRouteRunDetailResponse:
    summary = _build_route_run_summary(row=row, stop_rows=stop_rows)
    linked_bin_asset_ids = sorted(
        {
            str(stop.bin_asset_id or ticket.assigned_bin_asset_id)
            for stop, ticket in stop_rows
            if stop.bin_asset_id is not None or ticket.assigned_bin_asset_id is not None
        }
    )
    return BinRouteRunDetailResponse(
        route_run_id=summary.route_run_id,
        company_id=summary.company_id,
        route_label=summary.route_label,
        scheduled_date=summary.scheduled_date,
        status=summary.status,
        assigned_employee_id=summary.assigned_employee_id,
        notes=summary.notes,
        created_at=summary.created_at,
        stop_count=summary.stop_count,
        completed_ticket_count=summary.completed_ticket_count,
        dispatched_ticket_count=summary.dispatched_ticket_count,
        assigned_bin_count=summary.assigned_bin_count,
        linked_bin_asset_ids=linked_bin_asset_ids,
        stops=[
            BinRouteRunStopResponse(
                id=int(stop.id),
                sequence_index=None if stop.sequence_index is None else int(stop.sequence_index),
                bin_asset_id=None if stop.bin_asset_id is None else str(stop.bin_asset_id),
                stop_status=str(ticket.status),
                is_dispatched=str(ticket.status) == "DISPATCHED",
                is_completed=str(ticket.status) == "COMPLETED",
                is_skipped=str(ticket.status) == "CANCELLED",
                ticket=BinRouteRunTicketResponse(
                    bin_service_ticket_id=str(ticket.bin_service_ticket_id),
                    service_type=str(ticket.service_type),
                    status=str(ticket.status),
                    scheduled_date=ticket.scheduled_date,
                    scheduled_time_window=ticket.scheduled_time_window,
                    assigned_employee_id=None if ticket.assigned_employee_id is None else int(ticket.assigned_employee_id),
                    assigned_vehicle_label=ticket.assigned_vehicle_label,
                    customer_site_id=str(ticket.customer_site_id),
                    job_purchase_order_id=ticket.job_purchase_order_id,
                    dispatched_at=ticket.dispatched_at,
                    completed_at=ticket.completed_at,
                    completed_by_user_id=ticket.completed_by_user_id,
                    completion_notes=ticket.completion_notes,
                ),
            )
            for stop, ticket in stop_rows
        ],
    )


def _get_route_run_or_404(*, db: Session, company_id: int, route_run_id: str) -> BinRouteRun:
    row = (
        db.query(BinRouteRun)
        .filter(BinRouteRun.company_id == company_id, BinRouteRun.route_run_id == str(route_run_id))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Route run not found")
    return row


def _get_route_run_stop_rows(
    *,
    db: Session,
    company_id: int,
    route_run_ids: list[str] | None = None,
    route_run_id: str | None = None,
) -> list[tuple[BinRouteRunStop, BinServiceTicket]]:
    q = (
        db.query(BinRouteRunStop, BinServiceTicket)
        .join(BinServiceTicket, BinServiceTicket.bin_service_ticket_id == BinRouteRunStop.bin_service_ticket_id)
        .filter(
            BinRouteRunStop.company_id == company_id,
            BinServiceTicket.company_id == company_id,
        )
    )
    if route_run_ids is not None:
        if not route_run_ids:
            return []
        q = q.filter(BinRouteRunStop.route_run_id.in_(route_run_ids))
        q = q.order_by(
            BinRouteRunStop.route_run_id.asc(),
            BinRouteRunStop.sequence_index.asc().nullsfirst(),
            BinRouteRunStop.id.asc(),
        )
        return q.all()
    if route_run_id is not None:
        q = q.filter(BinRouteRunStop.route_run_id == str(route_run_id))
    return q.order_by(BinRouteRunStop.sequence_index.asc().nullsfirst(), BinRouteRunStop.id.asc()).all()


def _validate_route_run_assignee(*, db: Session, company_id: int, assigned_employee_id: int | None) -> None:
    if assigned_employee_id is None:
        return
    employee = (
        db.query(Employee)
        .filter(Employee.company_id == company_id, Employee.id == int(assigned_employee_id))
        .one_or_none()
    )
    if employee is None:
        raise ValueError("Employee not found")


def _validate_route_run_transition(*, current_status: str, new_status: str) -> None:
    allowed = {
        "PLANNED": {"ACTIVE", "CANCELLED"},
        "ACTIVE": {"COMPLETED", "CANCELLED"},
        "COMPLETED": set(),
        "CANCELLED": set(),
    }
    current = str(current_status)
    new = str(new_status)
    if current == new:
        return
    if new not in allowed.get(current, set()):
        raise ValueError(f"Invalid route run status transition: {current} -> {new}")


def _apply_route_run_status_change(
    *,
    db: Session,
    row: BinRouteRun,
    new_status: str,
) -> None:
    _validate_route_run_transition(current_status=str(row.status), new_status=str(new_status))
    if str(new_status) == "COMPLETED":
        incomplete_stop_count = (
            db.query(BinRouteRunStop)
            .join(BinServiceTicket, BinServiceTicket.bin_service_ticket_id == BinRouteRunStop.bin_service_ticket_id)
            .filter(
                BinRouteRunStop.company_id == int(row.company_id),
                BinRouteRunStop.route_run_id == str(row.route_run_id),
                BinServiceTicket.company_id == int(row.company_id),
                BinServiceTicket.status.notin_(["COMPLETED", "CANCELLED"]),
            )
            .count()
        )
        if incomplete_stop_count > 0:
            raise ValueError(
                f"Cannot complete route run while {incomplete_stop_count} stop(s) remain incomplete"
            )
    row.status = str(new_status)


def _load_route_run_detail(*, db: Session, company_id: int, route_run_id: str) -> BinRouteRunDetailResponse:
    row = _get_route_run_or_404(db=db, company_id=company_id, route_run_id=route_run_id)
    stop_rows = _get_route_run_stop_rows(db=db, company_id=company_id, route_run_id=route_run_id)
    return _build_route_run_detail(row=row, stop_rows=stop_rows)


def _get_route_run_stop_or_404(
    *,
    db: Session,
    company_id: int,
    route_run_id: str,
    stop_id: int,
) -> tuple[BinRouteRun, BinRouteRunStop, BinServiceTicket]:
    route_row = _get_route_run_or_404(db=db, company_id=company_id, route_run_id=route_run_id)
    stop_row = (
        db.query(BinRouteRunStop, BinServiceTicket)
        .join(BinServiceTicket, BinServiceTicket.bin_service_ticket_id == BinRouteRunStop.bin_service_ticket_id)
        .filter(
            BinRouteRunStop.company_id == company_id,
            BinServiceTicket.company_id == company_id,
            BinRouteRunStop.route_run_id == str(route_run_id),
            BinRouteRunStop.id == int(stop_id),
        )
        .one_or_none()
    )
    if stop_row is None:
        raise HTTPException(status_code=404, detail="Route run stop not found")
    stop, ticket = stop_row
    return route_row, stop, ticket


def _replace_route_run_stops(
    *,
    db: Session,
    company_id: int,
    route_run_id: str,
    payload: BinRouteRunStopsReplace,
) -> None:
    ticket_ids = [str(stop.service_ticket_id) for stop in payload.stops]
    if len(ticket_ids) != len(set(ticket_ids)):
        raise ValueError("Duplicate service ticket ids are not allowed")

    asset_ids = [str(stop.bin_asset_id) for stop in payload.stops if stop.bin_asset_id is not None]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("Duplicate bin asset ids are not allowed")

    for stop in payload.stops:
        if stop.sequence_index is not None and int(stop.sequence_index) < 1:
            raise ValueError("sequence_index must be at least 1")

    tickets_by_id: dict[str, BinServiceTicket] = {}
    if ticket_ids:
        tickets = (
            db.query(BinServiceTicket)
            .filter(
                BinServiceTicket.company_id == company_id,
                BinServiceTicket.bin_service_ticket_id.in_(ticket_ids),
            )
            .all()
        )
        tickets_by_id = {str(ticket.bin_service_ticket_id): ticket for ticket in tickets}
        missing_ticket_ids = [ticket_id for ticket_id in ticket_ids if ticket_id not in tickets_by_id]
        if missing_ticket_ids:
            raise ValueError("Service ticket not found")
        conflicting_ticket_route = (
            db.query(BinRouteRunStop)
            .filter(
                BinRouteRunStop.company_id == company_id,
                BinRouteRunStop.bin_service_ticket_id.in_(ticket_ids),
                BinRouteRunStop.route_run_id != str(route_run_id),
            )
            .first()
        )
        if conflicting_ticket_route is not None:
            raise ValueError("Service ticket already assigned to another route run")

    assets_by_id: dict[str, BinAsset] = {}
    if asset_ids:
        assets = (
            db.query(BinAsset)
            .filter(BinAsset.company_id == company_id, BinAsset.bin_asset_id.in_(asset_ids))
            .all()
        )
        assets_by_id = {str(asset.bin_asset_id): asset for asset in assets}
        missing_asset_ids = [asset_id for asset_id in asset_ids if asset_id not in assets_by_id]
        if missing_asset_ids:
            raise ValueError("Bin asset not found")

    existing_rows = (
        db.query(BinRouteRunStop)
        .filter(BinRouteRunStop.company_id == company_id, BinRouteRunStop.route_run_id == str(route_run_id))
        .order_by(BinRouteRunStop.id.asc())
        .all()
    )
    existing_by_ticket_id = {str(row.bin_service_ticket_id): row for row in existing_rows}
    incoming_ticket_ids = set(ticket_ids)

    for row in existing_rows:
        if str(row.bin_service_ticket_id) not in incoming_ticket_ids:
            db.delete(row)
    db.flush()

    for index, stop in enumerate(payload.stops, start=1):
        ticket_id = str(stop.service_ticket_id)
        ticket = tickets_by_id[ticket_id]
        row = existing_by_ticket_id.get(ticket_id)
        if row is None:
            row = BinRouteRunStop(
                company_id=company_id,
                route_run_id=str(route_run_id),
                bin_service_ticket_id=ticket_id,
            )
            db.add(row)
        row.sequence_index = stop.sequence_index if stop.sequence_index is not None else index
        row.bin_asset_id = stop.bin_asset_id if stop.bin_asset_id is not None else ticket.assigned_bin_asset_id


def _get_service_ticket_or_404(*, db: Session, company_id: int, ticket_id: str) -> BinServiceTicket:
    ticket = (
        db.query(BinServiceTicket)
        .filter(BinServiceTicket.company_id == company_id)
        .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
        .one_or_none()
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Service ticket not found")
    return ticket


def _dispatch_service_ticket(*, ticket: BinServiceTicket, dispatched_at: datetime | None = None) -> None:
    if str(ticket.status) in {"COMPLETED", "CANCELLED"}:
        raise ValueError("Cannot dispatch COMPLETED or CANCELLED ticket")
    _ensure_ticket_transition(current_status=str(ticket.status), new_status="DISPATCHED")
    ticket.status = "DISPATCHED"
    ticket.dispatched_at = dispatched_at or datetime.now(timezone.utc)


def _complete_service_ticket(
    *,
    db: Session,
    company_id: int,
    ticket: BinServiceTicket,
    completion_notes: str | None,
    completed_by_user_id: str,
) -> None:
    if str(ticket.status) == "COMPLETED":
        raise ValueError("Service ticket is already completed")

    _ensure_ticket_transition(current_status=str(ticket.status), new_status="COMPLETED")

    required_photo_by_service_type = {
        "DROP": "DROP_PROOF",
        "DROP_BIN": "DROP_PROOF",
        "SWAP": "SWAP_PROOF",
        "SWAP_BIN": "SWAP_PROOF",
        "PICKUP": "PICKUP_PROOF",
        "PICKUP_BIN": "PICKUP_PROOF",
    }
    required_photo_type = required_photo_by_service_type.get(str(ticket.service_type))
    if required_photo_type is not None:
        has_required_photo = (
            db.query(BinServicePhoto)
            .filter(BinServicePhoto.company_id == company_id)
            .filter(BinServicePhoto.bin_service_ticket_id == str(ticket.bin_service_ticket_id))
            .filter(BinServicePhoto.photo_type == required_photo_type)
            .first()
            is not None
        )
        if not has_required_photo:
            raise ValueError(f"Missing required proof photo: {required_photo_type}")

    ticket.status = "COMPLETED"
    ticket.completed_at = datetime.now(timezone.utc)
    ticket.completed_by_user_id = str(completed_by_user_id)
    ticket.completion_notes = completion_notes

    apply_ticket_completion_to_assigned_bins(
        db=db,
        company_id=company_id,
        ticket=ticket,
    )

    if ticket.assigned_bin_asset_id is not None:
        if str(ticket.service_type) == "DROP_BIN":
            record_drop(
                db=db,
                company_id=company_id,
                bin_id=str(ticket.assigned_bin_asset_id),
                customer_site_id=str(ticket.customer_site_id),
                related_ticket_id=str(ticket.bin_service_ticket_id),
                created_at=ticket.completed_at,
            )
        elif str(ticket.service_type) == "SWAP_BIN":
            record_swap(
                db=db,
                company_id=company_id,
                bin_id=str(ticket.assigned_bin_asset_id),
                customer_site_id=str(ticket.customer_site_id),
                related_ticket_id=str(ticket.bin_service_ticket_id),
                created_at=ticket.completed_at,
            )

    generate_invoice_for_completed_ticket(
        company_id=company_id,
        service_ticket_id=str(ticket.bin_service_ticket_id),
        db=db,
    )

    rendered_completion = render_completion_confirmation(
        db=db,
        company_id=company_id,
        ticket_row=ticket,
    )

    po_number: str | None = None
    if ticket.job_purchase_order_id is not None:
        po = (
            db.query(JobPurchaseOrder)
            .filter(JobPurchaseOrder.company_id == company_id)
            .filter(JobPurchaseOrder.job_purchase_order_id == str(ticket.job_purchase_order_id))
            .one_or_none()
        )
        if po is not None:
            po_number = str(po.po_number)

    site = (
        db.query(CustomerSite)
        .filter(CustomerSite.company_id == company_id)
        .filter(CustomerSite.customer_site_id == str(ticket.customer_site_id))
        .one_or_none()
    )
    if site is None:
        raise ValueError("Customer site not found")

    address_summary = ", ".join(
        [
            str(site.address_line_1),
            str(site.city),
            str(site.province),
            str(site.postal_code),
        ]
    )

    event_type = "WASTE_BIN_TICKET_COMPLETED_CONFIRMATION_READY"
    idempotency_key = f"{event_type}:{company_id}:{ticket.bin_service_ticket_id}"
    existing = (
        db.query(EventOutbox)
        .filter(EventOutbox.company_id == company_id)
        .filter(EventOutbox.idempotency_key == idempotency_key)
        .one_or_none()
    )
    if existing is None:
        db.add(
            EventOutbox(
                company_id=company_id,
                event_type=event_type,
                idempotency_key=idempotency_key,
                payload={
                    "company_id": company_id,
                    "bin_service_ticket_id": str(ticket.bin_service_ticket_id),
                    "service_type": str(ticket.service_type),
                    "customer_site_id": str(ticket.customer_site_id),
                    "address_summary": address_summary,
                    "completed_at": ticket.completed_at.isoformat() if ticket.completed_at is not None else None,
                    "po_number": po_number,
                    "rendered_subject": rendered_completion.subject,
                    "rendered_body": rendered_completion.body,
                },
            )
        )


def _skip_service_ticket(*, ticket: BinServiceTicket, skip_reason: str | None) -> None:
    if str(ticket.status) == "CANCELLED":
        raise ValueError("Service ticket is already cancelled")
    _ensure_ticket_transition(current_status=str(ticket.status), new_status="CANCELLED")
    ticket.status = "CANCELLED"
    ticket.completed_at = None
    ticket.completed_by_user_id = None
    if skip_reason is not None:
        ticket.completion_notes = skip_reason


@router.post("/customer-sites", response_model=CustomerSiteResponse)
def create_customer_site(
    payload: CustomerSiteCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = CustomerSite(company_id=company_id, **payload.model_dump())
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_customer_site(row)
    finally:
        db.close()


@router.get("/customer-sites", response_model=list[CustomerSiteResponse])
def list_customer_sites(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(CustomerSite)
            .filter(CustomerSite.company_id == company_id)
            .order_by(CustomerSite.created_at.desc(), CustomerSite.customer_site_id.asc())
            .all()
        )
        return [_serialize_customer_site(row) for row in rows]
    finally:
        db.close()


@router.post("/assets", response_model=BinAssetResponse)
def create_asset(
    payload: BinAssetCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        if payload.current_customer_site_id is not None:
            site = (
                db.query(CustomerSite)
                .filter(CustomerSite.company_id == company_id)
                .filter(CustomerSite.customer_site_id == str(payload.current_customer_site_id))
                .one_or_none()
            )
            if site is None:
                raise HTTPException(status_code=404, detail="Customer site not found")

        if payload.current_job_purchase_order_id is not None:
            po = (
                db.query(JobPurchaseOrder)
                .filter(JobPurchaseOrder.company_id == company_id)
                .filter(JobPurchaseOrder.job_purchase_order_id == str(payload.current_job_purchase_order_id))
                .one_or_none()
            )
            if po is None:
                raise HTTPException(status_code=404, detail="Job purchase order not found")

        row = BinAsset(
            company_id=company_id,
            bin_number=str(payload.bin_number),
            bin_type=str(payload.bin_type),
            bin_size=str(payload.bin_size),
            status=str(payload.status),
            current_customer_site_id=payload.current_customer_site_id,
            current_job_purchase_order_id=payload.current_job_purchase_order_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_asset(row)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        msg = str(getattr(exc, "orig", exc))
        if "uq_bin_assets_company_bin_number" in msg:
            raise HTTPException(status_code=409, detail="Bin number already exists for this company") from exc
        raise
    finally:
        db.close()


@router.get("/assets", response_model=list[BinAssetResponse])
def list_assets(
    request: Request,
    status: Literal["AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE"] | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        q = db.query(BinAsset).filter(BinAsset.company_id == company_id)
        if status is not None:
            q = q.filter(BinAsset.status == str(status))

        rows = q.order_by(BinAsset.created_at.desc(), BinAsset.bin_asset_id.asc()).all()
        return [_serialize_asset(row) for row in rows]
    finally:
        db.close()


@router.get("/routes", response_model=list[BinRouteRunSummaryResponse])
def list_route_runs(
    request: Request,
    scheduled_date: date | None = Query(default=None),
    status: Literal["PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"] | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        q = db.query(BinRouteRun).filter(BinRouteRun.company_id == company_id)
        if scheduled_date is not None:
            q = q.filter(BinRouteRun.scheduled_date == scheduled_date)
        if status is not None:
            q = q.filter(BinRouteRun.status == str(status))

        route_rows = q.order_by(BinRouteRun.scheduled_date.asc(), BinRouteRun.route_label.asc(), BinRouteRun.created_at.asc()).all()
        if not route_rows:
            return []

        route_ids = [str(row.route_run_id) for row in route_rows]
        stop_rows = _get_route_run_stop_rows(db=db, company_id=company_id, route_run_ids=route_ids)
        stops_by_route: dict[str, list[tuple[BinRouteRunStop, BinServiceTicket]]] = {route_id: [] for route_id in route_ids}
        for stop, ticket in stop_rows:
            stops_by_route[str(stop.route_run_id)].append((stop, ticket))

        return [
            _build_route_run_summary(row=row, stop_rows=stops_by_route.get(str(row.route_run_id), []))
            for row in route_rows
        ]
    finally:
        db.close()


@router.post("/routes", response_model=BinRouteRunDetailResponse)
def create_route_run(
    payload: BinRouteRunCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        try:
            _validate_route_run_assignee(
                db=db,
                company_id=company_id,
                assigned_employee_id=payload.assigned_employee_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        row = BinRouteRun(
            company_id=company_id,
            route_label=str(payload.route_label),
            scheduled_date=payload.scheduled_date,
            assigned_employee_id=payload.assigned_employee_id,
            notes=payload.notes,
        )
        db.add(row)
        db.commit()
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=str(row.route_run_id))
    finally:
        db.close()


@router.patch("/routes/{route_run_id}", response_model=BinRouteRunDetailResponse)
def patch_route_run(
    route_run_id: str,
    payload: BinRouteRunPatch,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = _get_route_run_or_404(db=db, company_id=company_id, route_run_id=route_run_id)
        updates = payload.model_dump(exclude_unset=True)
        if "assigned_employee_id" in updates:
            try:
                _validate_route_run_assignee(
                    db=db,
                    company_id=company_id,
                    assigned_employee_id=payload.assigned_employee_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

        if "status" in updates and payload.status is not None:
            try:
                _apply_route_run_status_change(db=db, row=row, new_status=str(payload.status))
            except ValueError as exc:
                detail = str(exc)
                if detail == "Cannot complete route run with incomplete tickets":
                    raise HTTPException(status_code=409, detail=detail) from exc
                raise HTTPException(status_code=409, detail=detail) from exc

        if "route_label" in updates:
            row.route_label = str(payload.route_label)
        if "scheduled_date" in updates:
            row.scheduled_date = payload.scheduled_date
        if "assigned_employee_id" in updates:
            row.assigned_employee_id = payload.assigned_employee_id
        if "notes" in updates:
            row.notes = payload.notes

        db.commit()
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=route_run_id)
    finally:
        db.close()


@router.get("/routes/{route_run_id}", response_model=BinRouteRunDetailResponse)
def get_route_run(
    route_run_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=route_run_id)
    finally:
        db.close()


@router.put("/routes/{route_run_id}/stops", response_model=BinRouteRunDetailResponse)
def replace_route_run_stops(
    route_run_id: str,
    payload: BinRouteRunStopsReplace,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = _get_route_run_or_404(db=db, company_id=company_id, route_run_id=route_run_id)
        if str(row.status) in {"COMPLETED", "CANCELLED"}:
            raise HTTPException(status_code=409, detail="Cannot modify stops for COMPLETED or CANCELLED route run")
        try:
            _replace_route_run_stops(
                db=db,
                company_id=company_id,
                route_run_id=route_run_id,
                payload=payload,
            )
        except ValueError as exc:
            detail = str(exc)
            if detail in {"Service ticket not found", "Bin asset not found"}:
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=409, detail=detail) from exc
        db.commit()
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=route_run_id)
    finally:
        db.close()


@router.post("/routes/{route_run_id}/dispatch", response_model=BinRouteRunDetailResponse)
def dispatch_route_run(
    route_run_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _permission=Depends(require_operations_permission(PrivilegedPermission.DISPATCH_MANAGE)),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = _get_route_run_or_404(db=db, company_id=company_id, route_run_id=route_run_id)
        try:
            _apply_route_run_status_change(db=db, row=row, new_status="ACTIVE")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=route_run_id)
    finally:
        db.close()


@router.post("/routes/{route_run_id}/complete", response_model=BinRouteRunDetailResponse)
def complete_route_run(
    route_run_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = _get_route_run_or_404(db=db, company_id=company_id, route_run_id=route_run_id)
        try:
            _apply_route_run_status_change(db=db, row=row, new_status="COMPLETED")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=route_run_id)
    finally:
        db.close()


@router.post("/routes/{route_run_id}/cancel", response_model=BinRouteRunDetailResponse)
def cancel_route_run(
    route_run_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = _get_route_run_or_404(db=db, company_id=company_id, route_run_id=route_run_id)
        try:
            _apply_route_run_status_change(db=db, row=row, new_status="CANCELLED")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=route_run_id)
    finally:
        db.close()


@router.post(
    "/routes/{route_run_id}/stops/{stop_id}/dispatch",
    response_model=BinRouteRunDetailResponse,
    dependencies=[Depends(require_company_module("dispatch"))],
)
def dispatch_route_run_stop(
    route_run_id: str,
    stop_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _permission=Depends(require_operations_permission(PrivilegedPermission.DISPATCH_MANAGE)),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        route_row, _stop_row, ticket = _get_route_run_stop_or_404(
            db=db,
            company_id=company_id,
            route_run_id=route_run_id,
            stop_id=stop_id,
        )
        if str(route_row.status) == "CANCELLED":
            raise HTTPException(status_code=409, detail="Cannot dispatch stop for CANCELLED route run")
        if str(route_row.status) == "COMPLETED":
            raise HTTPException(status_code=409, detail="Cannot dispatch stop for COMPLETED route run")
        try:
            _dispatch_service_ticket(ticket=ticket)
            if str(route_row.status) == "PLANNED":
                _apply_route_run_status_change(db=db, row=route_row, new_status="ACTIVE")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=route_run_id)
    finally:
        db.close()


@router.post("/routes/{route_run_id}/stops/{stop_id}/complete", response_model=BinRouteRunDetailResponse)
def complete_route_run_stop(
    route_run_id: str,
    stop_id: int,
    payload: BinServiceTicketCompleteCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        route_row, _stop_row, ticket = _get_route_run_stop_or_404(
            db=db,
            company_id=company_id,
            route_run_id=route_run_id,
            stop_id=stop_id,
        )
        if str(route_row.status) != "ACTIVE":
            raise HTTPException(status_code=409, detail="Cannot complete stop unless route run is ACTIVE")
        try:
            _complete_service_ticket(
                db=db,
                company_id=company_id,
                ticket=ticket,
                completion_notes=payload.completion_notes,
                completed_by_user_id=get_actor_user_id(request),
            )
        except ValueError as exc:
            detail = str(exc)
            if detail in {"Service ticket not found", "Customer site not found", "Bin asset not found"}:
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=409, detail=detail) from exc
        db.commit()
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=route_run_id)
    finally:
        db.close()


@router.post("/routes/{route_run_id}/stops/{stop_id}/skip", response_model=BinRouteRunDetailResponse)
def skip_route_run_stop(
    route_run_id: str,
    stop_id: int,
    payload: BinRouteRunStopSkipCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        route_row, _stop_row, ticket = _get_route_run_stop_or_404(
            db=db,
            company_id=company_id,
            route_run_id=route_run_id,
            stop_id=stop_id,
        )
        if str(route_row.status) == "COMPLETED":
            raise HTTPException(status_code=409, detail="Cannot skip stop for COMPLETED route run")
        if str(route_row.status) == "CANCELLED":
            raise HTTPException(status_code=409, detail="Cannot skip stop for CANCELLED route run")
        if str(route_row.status) != "ACTIVE":
            raise HTTPException(status_code=409, detail="Cannot skip stop unless route run is ACTIVE")
        try:
            _skip_service_ticket(ticket=ticket, skip_reason=payload.skip_reason)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        return _load_route_run_detail(db=db, company_id=company_id, route_run_id=route_run_id)
    finally:
        db.close()


@router.post("/assets/{bin_id}/return-to-yard", response_model=BinAssetResponse)
def return_asset_to_yard(
    bin_id: str,
    payload: BinReturnToYardCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(BinAsset)
            .filter(BinAsset.company_id == company_id)
            .filter(BinAsset.bin_asset_id == str(bin_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Bin asset not found")

        row.current_customer_site_id = None
        row.current_job_purchase_order_id = None
        row.status = "AVAILABLE"

        try:
            record_return(
                db=db,
                company_id=company_id,
                bin_id=str(row.bin_asset_id),
                from_location_type=str(payload.from_location_type),
                from_location_id=payload.from_location_id,
            )
        except ValueError as exc:
            detail = str(exc)
            if detail == "Invalid from location type":
                raise HTTPException(status_code=422, detail=detail) from exc
            raise HTTPException(status_code=409, detail=detail) from exc

        db.commit()
        db.refresh(row)
        return _serialize_asset(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/service-requests", response_model=BinServiceRequestResponse)
def create_bin_service_request(
    payload: BinServiceRequestCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        if payload.source_email_ingestion_event_id is not None:
            event = (
                db.query(EmailIngestionEvent)
                .filter(EmailIngestionEvent.company_id == company_id)
                .filter(EmailIngestionEvent.email_ingestion_event_id == str(payload.source_email_ingestion_event_id))
                .one_or_none()
            )
            if event is None:
                raise HTTPException(status_code=404, detail="Email ingestion event not found")

        try:
            row = create_service_request(
                db=db,
                company_id=company_id,
                customer_site_id=str(payload.customer_site_id),
                job_purchase_order_id=payload.job_purchase_order_id,
                request_type=payload.request_type,
                request_notes=payload.request_notes,
                requested_for=payload.requested_for,
                source_email_ingestion_event_id=payload.source_email_ingestion_event_id,
            )
        except ValueError as exc:
            detail = str(exc)
            if detail in {"Customer site not found", "Job purchase order not found"}:
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=422, detail=detail) from exc

        if payload.status is not None:
            row.status = str(payload.status)

        db.commit()
        db.refresh(row)
        return _serialize_request(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/service-requests", response_model=list[BinServiceRequestResponse])
def list_bin_service_requests(
    request: Request,
    status: Literal["OPEN", "SCHEDULED", "COMPLETED", "CANCELLED"] | None = Query(default=None),
    request_type: Literal["DROP", "SWAP", "PICKUP"] | None = Query(default=None),
    job_purchase_order_id: str | None = Query(default=None),
    source_email_ingestion_event_id: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        q = db.query(BinServiceRequest).filter(BinServiceRequest.company_id == company_id)
        if status is not None:
            q = q.filter(BinServiceRequest.status == str(status))
        if request_type is not None:
            q = q.filter(BinServiceRequest.request_type == str(request_type))
        if job_purchase_order_id is not None:
            q = q.filter(BinServiceRequest.job_purchase_order_id == str(job_purchase_order_id))
        if source_email_ingestion_event_id is not None:
            q = q.filter(
                BinServiceRequest.source_email_ingestion_event_id == str(source_email_ingestion_event_id)
            )

        rows = q.order_by(BinServiceRequest.created_at.desc(), BinServiceRequest.bin_service_request_id.asc()).all()
        return [_serialize_request(row) for row in rows]
    finally:
        db.close()


@router.post("/service-requests/from-email", response_model=BinServiceRequestResponse)
def create_bin_service_request_from_email_endpoint(
    payload: BinServiceRequestFromEmailCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        try:
            row = create_bin_service_request_from_email(
                db=db,
                company_id=company_id,
                email_ingestion_event_id=str(payload.email_ingestion_event_id),
                parsed_text_override=payload.parsed_text,
            )
        except ValueError as exc:
            detail = str(exc)
            if detail == "Email ingestion event not found":
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=422, detail=detail) from exc

        db.commit()
        db.refresh(row)
        return _serialize_request(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/service-tickets", response_model=BinServiceTicketResponse)
def create_bin_service_ticket(
    payload: BinServiceTicketCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        service_request = (
            db.query(BinServiceRequest)
            .filter(BinServiceRequest.company_id == company_id)
            .filter(BinServiceRequest.bin_service_request_id == str(payload.bin_service_request_id))
            .one_or_none()
        )
        if service_request is None:
            raise HTTPException(status_code=404, detail="Service request not found")

        site = (
            db.query(CustomerSite)
            .filter(CustomerSite.company_id == company_id)
            .filter(CustomerSite.customer_site_id == str(payload.customer_site_id))
            .one_or_none()
        )
        if site is None:
            raise HTTPException(status_code=404, detail="Customer site not found")

        if payload.job_purchase_order_id is not None:
            po = (
                db.query(JobPurchaseOrder)
                .filter(JobPurchaseOrder.company_id == company_id)
                .filter(JobPurchaseOrder.job_purchase_order_id == str(payload.job_purchase_order_id))
                .one_or_none()
            )
            if po is None:
                raise HTTPException(status_code=404, detail="Job purchase order not found")

        try:
            _validate_assignment_refs(
                db=db,
                company_id=company_id,
                assigned_bin_asset_id=payload.assigned_bin_asset_id,
                assigned_employee_id=payload.assigned_employee_id,
            )
        except ValueError as exc:
            detail = str(exc)
            if detail in {"Bin asset not found", "Employee not found"}:
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=409, detail=detail) from exc

        if str(payload.status) == "COMPLETED":
            raise HTTPException(status_code=409, detail="Use /complete endpoint to complete a ticket")

        row = BinServiceTicket(
            company_id=company_id,
            bin_service_request_id=str(payload.bin_service_request_id),
            customer_site_id=str(payload.customer_site_id),
            job_purchase_order_id=payload.job_purchase_order_id,
            assigned_bin_asset_id=payload.assigned_bin_asset_id,
            assigned_employee_id=payload.assigned_employee_id,
            assigned_vehicle_label=payload.assigned_vehicle_label,
            service_type=str(payload.service_type),
            priority=str(payload.priority),
            scheduled_for=payload.scheduled_for,
            scheduled_date=payload.scheduled_date,
            scheduled_time_window=payload.scheduled_time_window,
            status=str(payload.status),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_ticket(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/service-tickets", response_model=list[BinServiceTicketResponse])
def list_bin_service_tickets(
    request: Request,
    status: Literal["OPEN", "SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"] | None = Query(default=None),
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] | None = Query(default=None),
    scheduled_date: date | None = Query(default=None),
    assigned_employee_id: int | None = Query(default=None),
    job_purchase_order_id: str | None = Query(default=None),
    customer_site_id: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        q = db.query(BinServiceTicket).filter(BinServiceTicket.company_id == company_id)
        if status is not None:
            q = q.filter(BinServiceTicket.status == str(status))
        if priority is not None:
            q = q.filter(BinServiceTicket.priority == str(priority))
        if scheduled_date is not None:
            q = q.filter(BinServiceTicket.scheduled_date == scheduled_date)
        if assigned_employee_id is not None:
            q = q.filter(BinServiceTicket.assigned_employee_id == int(assigned_employee_id))
        if job_purchase_order_id is not None:
            q = q.filter(BinServiceTicket.job_purchase_order_id == str(job_purchase_order_id))
        if customer_site_id is not None:
            q = q.filter(BinServiceTicket.customer_site_id == str(customer_site_id))

        rows = q.order_by(BinServiceTicket.created_at.desc(), BinServiceTicket.bin_service_ticket_id.asc()).all()
        return [_serialize_ticket(row) for row in rows]
    finally:
        db.close()


@router.post("/service-tickets/{ticket_id}/schedule", response_model=BinServiceTicketResponse)
def schedule_bin_service_ticket(
    ticket_id: str,
    payload: BinServiceTicketScheduleCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        ticket = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
            .one_or_none()
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="Service ticket not found")

        try:
            _ensure_ticket_transition(current_status=str(ticket.status), new_status="SCHEDULED")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        ticket.status = "SCHEDULED"
        ticket.scheduled_date = payload.scheduled_date
        ticket.scheduled_time_window = payload.scheduled_time_window
        ticket.priority = str(payload.priority)

        db.commit()
        db.refresh(ticket)
        return _serialize_ticket(ticket)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.post(
    "/service-tickets/{ticket_id}/dispatch",
    response_model=BinServiceTicketResponse,
    dependencies=[Depends(require_company_module("dispatch"))],
)
def dispatch_bin_service_ticket(
    ticket_id: str,
    payload: BinServiceTicketDispatchCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _permission=Depends(require_operations_permission(PrivilegedPermission.DISPATCH_MANAGE)),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        ticket = _get_service_ticket_or_404(db=db, company_id=company_id, ticket_id=ticket_id)
        try:
            _dispatch_service_ticket(ticket=ticket, dispatched_at=payload.dispatched_at)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        db.commit()
        db.refresh(ticket)
        return _serialize_ticket(ticket)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.patch("/service-tickets/{ticket_id}/assignment", response_model=BinServiceTicketResponse)
def patch_bin_service_ticket_assignment(
    ticket_id: str,
    payload: BinServiceTicketAssignmentPatch,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        ticket = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
            .one_or_none()
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="Service ticket not found")

        if str(ticket.status) in {"COMPLETED", "CANCELLED"}:
            raise HTTPException(status_code=409, detail="Cannot update assignment for COMPLETED or CANCELLED ticket")

        try:
            _validate_assignment_refs(
                db=db,
                company_id=company_id,
                assigned_bin_asset_id=payload.assigned_bin_asset_id,
                assigned_employee_id=payload.assigned_employee_id,
            )
        except ValueError as exc:
            detail = str(exc)
            if detail in {"Bin asset not found", "Employee not found"}:
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=409, detail=detail) from exc

        ticket.assigned_bin_asset_id = payload.assigned_bin_asset_id
        ticket.assigned_employee_id = payload.assigned_employee_id
        ticket.assigned_vehicle_label = payload.assigned_vehicle_label

        db.commit()
        db.refresh(ticket)
        return _serialize_ticket(ticket)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/service-tickets/queue", response_model=list[BinServiceTicketResponse])
def list_bin_service_ticket_queue(
    request: Request,
    status: Literal["OPEN", "SCHEDULED", "DISPATCHED"] | None = Query(default=None),
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] | None = Query(default=None),
    scheduled_date: date | None = Query(default=None),
    assigned_employee_id: int | None = Query(default=None),
    job_purchase_order_id: str | None = Query(default=None),
    customer_site_id: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        q = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.status.notin_(["COMPLETED", "CANCELLED"]))
        )
        if status is not None:
            q = q.filter(BinServiceTicket.status == str(status))
        if priority is not None:
            q = q.filter(BinServiceTicket.priority == str(priority))
        if scheduled_date is not None:
            q = q.filter(BinServiceTicket.scheduled_date == scheduled_date)
        if assigned_employee_id is not None:
            q = q.filter(BinServiceTicket.assigned_employee_id == int(assigned_employee_id))
        if job_purchase_order_id is not None:
            q = q.filter(BinServiceTicket.job_purchase_order_id == str(job_purchase_order_id))
        if customer_site_id is not None:
            q = q.filter(BinServiceTicket.customer_site_id == str(customer_site_id))

        rows = q.order_by(BinServiceTicket.created_at.desc(), BinServiceTicket.bin_service_ticket_id.asc()).all()
        return [_serialize_ticket(row) for row in rows]
    finally:
        db.close()


@router.get("/service-tickets/today", response_model=list[BinServiceTicketResponse])
def list_bin_service_ticket_today(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        today = date.today()
        priority_rank = {
            "URGENT": 1,
            "HIGH": 2,
            "NORMAL": 3,
            "LOW": 4,
        }

        rows = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.scheduled_date == today)
            .filter(BinServiceTicket.status.notin_(["COMPLETED", "CANCELLED"]))
            .all()
        )

        rows = sorted(
            rows,
            key=lambda r: (
                priority_rank.get(str(r.priority), 99),
                "" if r.scheduled_time_window is None else str(r.scheduled_time_window),
                r.created_at,
            ),
        )

        return [_serialize_ticket(row) for row in rows]
    finally:
        db.close()


@router.post("/service-tickets/{ticket_id}/photos", response_model=BinServicePhotoResponse)
def add_bin_service_ticket_photo(
    ticket_id: str,
    payload: BinServicePhotoCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        ticket = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
            .one_or_none()
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="Service ticket not found")

        row = BinServicePhoto(
            company_id=company_id,
            bin_service_ticket_id=str(ticket_id),
            photo_type=str(payload.photo_type),
            storage_key=str(payload.storage_key),
            captured_at=payload.captured_at,
            captured_lat=payload.captured_lat,
            captured_lng=payload.captured_lng,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_service_photo(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/service-tickets/{ticket_id}/photos", response_model=list[BinServicePhotoResponse])
def list_bin_service_ticket_photos(
    ticket_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        ticket = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
            .one_or_none()
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="Service ticket not found")

        rows = (
            db.query(BinServicePhoto)
            .filter(BinServicePhoto.company_id == company_id)
            .filter(BinServicePhoto.bin_service_ticket_id == str(ticket_id))
            .order_by(BinServicePhoto.captured_at.desc(), BinServicePhoto.bin_service_photo_id.asc())
            .all()
        )
        return [_serialize_service_photo(row) for row in rows]
    finally:
        db.close()


@router.post("/service-tickets/{ticket_id}/complete", response_model=BinServiceTicketResponse)
def complete_bin_service_ticket(
    ticket_id: str,
    payload: BinServiceTicketCompleteCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        ticket = _get_service_ticket_or_404(db=db, company_id=company_id, ticket_id=ticket_id)
        try:
            _complete_service_ticket(
                db=db,
                company_id=company_id,
                ticket=ticket,
                completion_notes=payload.completion_notes,
                completed_by_user_id=get_actor_user_id(request),
            )
        except ValueError as exc:
            detail = str(exc)
            if detail in {"Service ticket not found", "Customer site not found", "Bin asset not found"}:
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=409, detail=detail) from exc

        db.commit()
        db.refresh(ticket)
        return _serialize_ticket(ticket)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/service-tickets/{ticket_id}/invoice", response_model=InvoiceResponse)
def get_service_ticket_invoice(
    ticket_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        invoice = (
            db.query(Invoice)
            .filter(Invoice.company_id == company_id)
            .filter(Invoice.service_ticket_id == str(ticket_id))
            .one_or_none()
        )
        if invoice is None:
            raise HTTPException(status_code=404, detail="Invoice not found")

        lines = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.invoice_id == str(invoice.invoice_id))
            .order_by(InvoiceLine.invoice_line_id.asc())
            .all()
        )
        return _serialize_invoice(invoice, lines)
    finally:
        db.close()


@router.get("/service-requests/{request_id}/ack-preview", response_model=WasteBinNotificationPreviewResponse)
def get_service_request_ack_preview(
    request_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(BinServiceRequest)
            .filter(BinServiceRequest.company_id == company_id)
            .filter(BinServiceRequest.bin_service_request_id == str(request_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Service request not found")

        rendered = render_request_acknowledgement(db=db, company_id=company_id, request_row=row)
        return WasteBinNotificationPreviewResponse(
            message_type=rendered.message_type,
            subject=rendered.subject,
            body=rendered.body,
        )
    finally:
        db.close()


@router.get("/service-tickets/{ticket_id}/completion-preview", response_model=WasteBinNotificationPreviewResponse)
def get_service_ticket_completion_preview(
    ticket_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Service ticket not found")

        rendered = render_completion_confirmation(db=db, company_id=company_id, ticket_row=row)
        return WasteBinNotificationPreviewResponse(
            message_type=rendered.message_type,
            subject=rendered.subject,
            body=rendered.body,
        )
    finally:
        db.close()


@router.get("/service-tickets/{ticket_id}/work-order", response_model=WasteBinNotificationPreviewResponse)
def get_service_ticket_work_order_preview(
    ticket_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Service ticket not found")

        rendered = render_dispatch_work_order(db=db, company_id=company_id, ticket_row=row)
        return WasteBinNotificationPreviewResponse(
            message_type=rendered.message_type,
            subject=rendered.subject,
            body=rendered.body,
        )
    finally:
        db.close()


@router.post("/service-tickets/{ticket_id}/landfill-trips", response_model=LandfillTripResponse)
def create_landfill_trip_for_ticket(
    ticket_id: str,
    payload: LandfillTripCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        try:
            row = record_landfill_trip(
                company_id=company_id,
                bin_service_ticket_id=str(ticket_id),
                bin_asset_id=str(payload.bin_asset_id),
                dump_site_name=str(payload.dump_site_name),
                dump_cost_cents=int(payload.dump_cost_cents),
                km_driven=payload.km_driven,
                receipt_photo_id=payload.receipt_photo_id,
                db=db,
            )
        except ValueError as exc:
            detail = str(exc)
            if detail in {
                "Service ticket not found",
                "Bin asset not found",
                "Receipt photo not found",
                "Job purchase order not found",
            }:
                raise HTTPException(status_code=404, detail=detail) from exc
            if detail in {
                "Service ticket must be COMPLETED before recording landfill trip",
                "Landfill trip already exists for ticket",
                "Service ticket must be linked to a job purchase order for costing",
                "Receipt photo must belong to the same service ticket",
                "receipt_photo_id must reference a RECEIPT photo",
            }:
                raise HTTPException(status_code=409, detail=detail) from exc
            raise HTTPException(status_code=422, detail=detail) from exc

        db.commit()
        db.refresh(row)
        return _serialize_landfill_trip(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/service-tickets/{ticket_id}/landfill-trips", response_model=list[LandfillTripResponse])
def list_landfill_trips_for_ticket(
    ticket_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        ticket = (
            db.query(BinServiceTicket)
            .filter(BinServiceTicket.company_id == company_id)
            .filter(BinServiceTicket.bin_service_ticket_id == str(ticket_id))
            .one_or_none()
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="Service ticket not found")

        rows = (
            db.query(LandfillTrip)
            .filter(LandfillTrip.company_id == company_id)
            .filter(LandfillTrip.bin_service_ticket_id == str(ticket_id))
            .order_by(LandfillTrip.created_at.desc(), LandfillTrip.landfill_trip_id.asc())
            .all()
        )
        return [_serialize_landfill_trip(row) for row in rows]
    finally:
        db.close()


@router.get("/bins/{bin_id}/history", response_model=list[BinMovementResponse])
def list_bin_history(
    bin_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        asset = (
            db.query(BinAsset)
            .filter(BinAsset.company_id == company_id)
            .filter(BinAsset.bin_asset_id == str(bin_id))
            .one_or_none()
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="Bin asset not found")

        rows = (
            db.query(BinMovement)
            .filter(BinMovement.company_id == company_id)
            .filter(BinMovement.bin_id == str(bin_id))
            .order_by(BinMovement.created_at.desc(), BinMovement.id.desc())
            .all()
        )
        return [_serialize_movement(row) for row in rows]
    finally:
        db.close()


@router.get("/movements", response_model=list[BinMovementResponse])
def list_bin_movements(
    request: Request,
    bin_id: str | None = Query(default=None),
    movement_type: Literal["DROP", "SWAP_OUT", "SWAP_IN", "LANDFILL_DUMP", "RETURN_TO_YARD"] | None = Query(
        default=None
    ),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        q = db.query(BinMovement).filter(BinMovement.company_id == company_id)
        if bin_id is not None:
            q = q.filter(BinMovement.bin_id == str(bin_id))
        if movement_type is not None:
            q = q.filter(BinMovement.movement_type == str(movement_type))

        rows = q.order_by(BinMovement.created_at.desc(), BinMovement.id.desc()).all()
        return [_serialize_movement(row) for row in rows]
    finally:
        db.close()

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class CustomerSiteCreate(BaseModel):
    customer_name: str
    site_name: str | None = None
    address_line_1: str
    city: str
    province: str
    postal_code: str
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class CustomerSiteResponse(BaseModel):
    customer_site_id: str
    company_id: int
    customer_name: str
    site_name: str | None
    address_line_1: str
    city: str
    province: str
    postal_code: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    created_at: datetime


class BinAssetCreate(BaseModel):
    bin_number: str
    bin_type: str
    bin_size: str
    status: Literal["AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE"] = "AVAILABLE"
    current_customer_site_id: str | None = None
    current_job_purchase_order_id: str | None = None


class BinAssetResponse(BaseModel):
    bin_asset_id: str
    company_id: int
    bin_number: str
    bin_type: str
    bin_size: str
    status: Literal["AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE"]
    current_customer_site_id: str | None
    current_job_purchase_order_id: str | None
    created_at: datetime


class BinServiceRequestCreate(BaseModel):
    customer_site_id: str
    job_purchase_order_id: str | None = None
    source_email_ingestion_event_id: str | None = None
    request_type: Literal["DROP", "SWAP", "PICKUP"]
    requested_for: datetime | None = None
    status: Literal["OPEN", "SCHEDULED", "COMPLETED", "CANCELLED"] | None = None
    request_notes: str | None = None


class BinServiceRequestResponse(BaseModel):
    bin_service_request_id: str
    company_id: int
    customer_site_id: str | None
    job_purchase_order_id: str | None
    source_email_ingestion_event_id: str | None
    request_type: Literal["DROP", "SWAP", "PICKUP"]
    requested_for: datetime | None
    status: Literal["OPEN", "SCHEDULED", "COMPLETED", "CANCELLED"]
    request_notes: str | None
    parsed_confidence: float | None
    created_at: datetime


class BinServiceRequestFromEmailCreate(BaseModel):
    email_ingestion_event_id: str
    parsed_text: str | None = None


class BinServiceTicketCreate(BaseModel):
    bin_service_request_id: str
    customer_site_id: str
    job_purchase_order_id: str | None = None
    assigned_bin_asset_id: str | None = None
    assigned_employee_id: int | None = None
    assigned_vehicle_label: str | None = None
    service_type: Literal["DROP", "SWAP", "PICKUP", "DROP_BIN", "SWAP_BIN", "PICKUP_BIN", "LANDFILL_DUMP"]
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"
    scheduled_for: datetime | None = None
    scheduled_date: date | None = None
    scheduled_time_window: str | None = None
    status: Literal["OPEN", "SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"] = "OPEN"
    completed_at: datetime | None = None
    completion_notes: str | None = None


class BinServiceTicketResponse(BaseModel):
    bin_service_ticket_id: str
    company_id: int
    bin_service_request_id: str
    customer_site_id: str
    job_purchase_order_id: str | None
    assigned_bin_asset_id: str | None
    assigned_employee_id: int | None
    assigned_vehicle_label: str | None
    service_type: Literal["DROP", "SWAP", "PICKUP", "DROP_BIN", "SWAP_BIN", "PICKUP_BIN", "LANDFILL_DUMP"]
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"]
    scheduled_for: datetime | None
    scheduled_date: date | None
    scheduled_time_window: str | None
    status: Literal["OPEN", "SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"]
    dispatched_at: datetime | None
    completed_at: datetime | None
    completed_by_user_id: str | None
    completion_notes: str | None
    created_at: datetime


class BinServicePhotoCreate(BaseModel):
    photo_type: Literal["DROP_PROOF", "SWAP_PROOF", "PICKUP_PROOF", "RECEIPT"]
    storage_key: str
    captured_at: datetime
    captured_lat: float | None = None
    captured_lng: float | None = None


class BinServicePhotoResponse(BaseModel):
    bin_service_photo_id: str
    company_id: int
    bin_service_ticket_id: str
    photo_type: Literal["DROP_PROOF", "SWAP_PROOF", "PICKUP_PROOF", "RECEIPT"]
    storage_key: str
    captured_at: datetime
    captured_lat: float | None
    captured_lng: float | None
    created_at: datetime


class BinServiceTicketCompleteCreate(BaseModel):
    completion_notes: str | None = None


class BinServiceTicketScheduleCreate(BaseModel):
    scheduled_date: date
    scheduled_time_window: str | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"


class BinServiceTicketDispatchCreate(BaseModel):
    dispatched_at: datetime | None = None


class BinServiceTicketAssignmentPatch(BaseModel):
    assigned_bin_asset_id: str | None = None
    assigned_employee_id: int | None = None
    assigned_vehicle_label: str | None = None


class LandfillTripCreate(BaseModel):
    bin_asset_id: str
    dump_site_name: str
    dump_cost_cents: int
    km_driven: float
    receipt_photo_id: str | None = None


class LandfillTripResponse(BaseModel):
    landfill_trip_id: str
    company_id: int
    bin_service_ticket_id: str
    bin_asset_id: str
    dump_site_name: str
    receipt_photo_id: str | None
    dump_cost_cents: int
    km_driven: float
    created_at: datetime
    completed_at: datetime


class BinMovementResponse(BaseModel):
    id: str
    company_id: int
    bin_id: str
    movement_type: Literal["DROP", "SWAP_OUT", "SWAP_IN", "LANDFILL_DUMP", "RETURN_TO_YARD"]
    from_location_type: Literal["SITE", "LANDFILL", "YARD"]
    from_location_id: str | None
    to_location_type: Literal["SITE", "LANDFILL", "YARD"]
    to_location_id: str | None
    related_ticket_id: str | None
    related_landfill_trip_id: str | None
    created_at: datetime


class BinReturnToYardCreate(BaseModel):
    from_location_type: Literal["SITE", "LANDFILL", "YARD"] = "SITE"
    from_location_id: str | None = None


class WasteBinNotificationPreviewResponse(BaseModel):
    message_type: str
    subject: str
    body: str


class BinRouteRunSummaryResponse(BaseModel):
    route_run_id: str
    company_id: int
    route_label: str
    scheduled_date: date
    status: Literal["PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"]
    assigned_employee_id: int | None
    notes: str | None
    created_at: datetime
    stop_count: int
    completed_ticket_count: int
    dispatched_ticket_count: int
    assigned_bin_count: int


class BinRouteRunCreate(BaseModel):
    route_label: str
    scheduled_date: date
    assigned_employee_id: int | None = None
    notes: str | None = None


class BinRouteRunPatch(BaseModel):
    route_label: str | None = None
    scheduled_date: date | None = None
    assigned_employee_id: int | None = None
    notes: str | None = None
    status: Literal["PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"] | None = None


class BinRouteRunTicketResponse(BaseModel):
    bin_service_ticket_id: str
    service_type: Literal["DROP", "SWAP", "PICKUP", "DROP_BIN", "SWAP_BIN", "PICKUP_BIN", "LANDFILL_DUMP"]
    status: Literal["OPEN", "SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"]
    scheduled_date: date | None
    scheduled_time_window: str | None
    assigned_employee_id: int | None
    assigned_vehicle_label: str | None
    customer_site_id: str
    job_purchase_order_id: str | None
    dispatched_at: datetime | None
    completed_at: datetime | None
    completed_by_user_id: str | None
    completion_notes: str | None


class BinRouteRunStopResponse(BaseModel):
    id: int
    sequence_index: int | None
    bin_asset_id: str | None
    stop_status: Literal["OPEN", "SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"]
    is_dispatched: bool
    is_completed: bool
    is_skipped: bool
    ticket: BinRouteRunTicketResponse


class BinRouteRunStopUpsert(BaseModel):
    service_ticket_id: str
    sequence_index: int | None = None
    bin_asset_id: str | None = None


class BinRouteRunStopsReplace(BaseModel):
    stops: list[BinRouteRunStopUpsert]


class BinRouteRunStopSkipCreate(BaseModel):
    skip_reason: str | None = None


class BinRouteRunDetailResponse(BaseModel):
    route_run_id: str
    company_id: int
    route_label: str
    scheduled_date: date
    status: Literal["PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"]
    assigned_employee_id: int | None
    notes: str | None
    created_at: datetime
    stop_count: int
    completed_ticket_count: int
    dispatched_ticket_count: int
    assigned_bin_count: int
    linked_bin_asset_ids: list[str]
    stops: list[BinRouteRunStopResponse]

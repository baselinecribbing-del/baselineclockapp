from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from app.database import SessionLocal
from app.deps.access_control import require_operations_access
from app.deps.auth import require_auth
from app.deps.entitlements import CompanyAccessContext, get_company_access_context, require_company_module
from app.services.dashboard_overview_service import (
    get_core_dashboard_overview,
    get_foundations_dashboard_overview,
    get_waste_bins_dashboard_overview,
)

router = APIRouter(prefix="/command-center", tags=["Command Center"])


class KpiBlock(BaseModel):
    active_crews: int
    employees_clocked_in: int
    hours_logged_today: float
    open_jobs: int
    payroll_pending: int
    safety_alerts: int


class CrewStatusRow(BaseModel):
    crew_id: str
    crew_name: str
    active_members: int
    clocked_in_members: int


class ActiveJobRow(BaseModel):
    job_id: int
    job_name: str
    address_label: str | None
    assigned_today: int


class ActivityRow(BaseModel):
    activity_type: str
    count: int


class SnapshotBlock(BaseModel):
    today_labor_cost_cents: int
    pending_payroll_runs: int
    draft_or_issued_invoices: int


class ReplaceValueBlock(BaseModel):
    replacing_today: list[str]


class PayrollReadinessSummaryBlock(BaseModel):
    pending_time_approvals_count: int
    rejected_time_entries_count: int
    employees_not_payroll_ready_count: int
    employees_missing_tax_setup_count: int
    employees_missing_payment_method_count: int
    approved_hours_ready_count: float | None = None


class CommandCenterOverview(BaseModel):
    module_context: Literal["core"] = "core"
    kpis: KpiBlock
    crew_status: list[CrewStatusRow]
    active_jobs: list[ActiveJobRow]
    todays_activity: list[ActivityRow]
    cost_snapshot: SnapshotBlock
    payroll_invoices_snapshot: SnapshotBlock
    payroll_readiness_summary: PayrollReadinessSummaryBlock
    replace_value: ReplaceValueBlock


class WasteBinsDashboardBinRow(BaseModel):
    bin_asset_id: str
    bin_number: str
    bin_type: str
    bin_size: str
    status: str
    current_customer_site_id: str | None
    current_job_purchase_order_id: str | None


class WasteBinsScheduledPickupRow(BaseModel):
    bin_service_ticket_id: str
    service_type: str
    status: str
    scheduled_date: str | None
    scheduled_time_window: str | None
    assigned_employee_id: int | None
    assigned_vehicle_label: str | None


class WasteBinsDispatchBoardRow(WasteBinsScheduledPickupRow):
    assigned_bin_asset_id: str | None


class WasteBinsActiveBinsBlock(BaseModel):
    count: int
    rows: list[WasteBinsDashboardBinRow]


class WasteBinsScheduledPickupsBlock(BaseModel):
    count: int
    rows: list[WasteBinsScheduledPickupRow]


class WasteBinsDispatchBoardBlock(BaseModel):
    rows: list[WasteBinsDispatchBoardRow]


class WasteBinsServiceTicketsBlock(BaseModel):
    counts_by_status: dict[str, int]
    open_request_count: int


class WasteBinsLandfillRunRow(BaseModel):
    landfill_trip_id: str
    bin_service_ticket_id: str
    bin_asset_id: str
    dump_site_name: str
    dump_cost_cents: int
    completed_at: str


class WasteBinsLandfillRunsBlock(BaseModel):
    rows: list[WasteBinsLandfillRunRow]


class WasteBinsAssetStatusBlock(BaseModel):
    counts_by_status: dict[str, int]


class WasteBinsRouteActivityBlock(BaseModel):
    scheduled_today_count: int
    dispatched_today_count: int
    completed_today_count: int
    rows: list[dict]


class WasteBinsDashboardOverview(BaseModel):
    module_context: Literal["waste_bins"] = "waste_bins"
    active_bins: WasteBinsActiveBinsBlock
    scheduled_pickups: WasteBinsScheduledPickupsBlock
    dispatch_board: WasteBinsDispatchBoardBlock
    service_tickets: WasteBinsServiceTicketsBlock
    landfill_runs: WasteBinsLandfillRunsBlock
    asset_status: WasteBinsAssetStatusBlock
    route_activity: WasteBinsRouteActivityBlock


class FoundationsHazardRow(BaseModel):
    hazard_assessment_id: str
    job_id: int
    job_name: str
    scope_id: int | None
    assessment_date: date
    created_at: datetime
    issue_photo_count: int


class FoundationsHazardAssessmentsBlock(BaseModel):
    open_count: int | None
    needs_review_count: int | None
    recent_rows: list[FoundationsHazardRow]


class FoundationsToolboxRow(BaseModel):
    toolbox_meeting_id: str
    job_id: int | None
    job_name: str | None
    scope_id: int | None
    meeting_date: date
    attendee_count: int | None
    created_at: datetime


class FoundationsAttendanceSummaryBlock(BaseModel):
    meeting_count: int
    meetings_with_attendee_count: int
    attendee_total: int | None
    attendee_average: float | None


class FoundationsToolboxMeetingsBlock(BaseModel):
    recent_rows: list[FoundationsToolboxRow]
    attendance_summary: FoundationsAttendanceSummaryBlock | None
    compliance_summary: dict | None


class FoundationsBlueprintDeliveryRow(BaseModel):
    job_document_delivery_id: str
    job_document_id: str
    job_id: int | None
    job_name: str | None
    scope_id: int | None
    file_name: str
    document_type: str
    employee_id: int
    delivered_at: datetime
    viewed_at: datetime | None


class FoundationsBlueprintDeliveryBlock(BaseModel):
    recent_rows: list[FoundationsBlueprintDeliveryRow]
    pending_acknowledgement_count: int


class FoundationsMessageRow(BaseModel):
    foundations_message_id: str
    job_id: int | None
    job_name: str | None
    scope_id: int | None
    employee_id: int | None
    message_type: str
    subject: str | None
    created_at: datetime


class FoundationsJobCommunicationBlock(BaseModel):
    recent_rows: list[FoundationsMessageRow]
    unresolved_thread_count: int | None


class FoundationsProgressIssueRow(BaseModel):
    foundation_activity_id: str
    job_id: int
    job_name: str
    scope_id: int
    employee_id: int
    activity_type: str
    notes: str | None
    created_at: datetime


class FoundationsProgressIssuesBlock(BaseModel):
    recent_rows: list[FoundationsProgressIssueRow]
    blocker_count: int


class FoundationsDashboardOverview(BaseModel):
    module_context: Literal["foundations"] = "foundations"
    hazard_assessments: FoundationsHazardAssessmentsBlock
    toolbox_meetings: FoundationsToolboxMeetingsBlock
    blueprint_delivery: FoundationsBlueprintDeliveryBlock
    job_communication: FoundationsJobCommunicationBlock
    progress_issues: FoundationsProgressIssuesBlock


@router.get("/overview", response_model=Union[CommandCenterOverview, WasteBinsDashboardOverview, FoundationsDashboardOverview])
def get_command_center_overview(
    request: Request,
    module_context: Literal["core", "waste_bins", "foundations"] = Query(default="core"),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _operations=Depends(require_operations_access),
    company_access: CompanyAccessContext = Depends(get_company_access_context),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    company_id = int(request.state.company_id)

    if module_context == "waste_bins":
        require_company_module("waste_bins")(company_access)
    elif module_context == "foundations":
        require_company_module("foundations")(company_access)
    else:
        require_company_module("field")(company_access)

    db = SessionLocal()
    try:
        if module_context == "waste_bins":
            return WasteBinsDashboardOverview(**get_waste_bins_dashboard_overview(db=db, company_id=company_id))
        if module_context == "foundations":
            return FoundationsDashboardOverview(**get_foundations_dashboard_overview(db=db, company_id=company_id))
        return CommandCenterOverview(**get_core_dashboard_overview(db=db, company_id=company_id))
    finally:
        db.close()

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.bin_asset import BinAsset
from app.models.bin_service_request import BinServiceRequest
from app.models.bin_service_ticket import BinServiceTicket
from app.models.crew import Crew
from app.models.crew_assignment import CrewAssignment
from app.models.crew_member import CrewMember
from app.models.foundation_activity_log import FoundationActivityLog
from app.models.foundations_message import FoundationsMessage
from app.models.invoice import Invoice
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.job_document import JobDocument
from app.models.job_document_delivery import JobDocumentDelivery
from app.models.landfill_trip import LandfillTrip
from app.models.payroll_run import PayrollRun
from app.models.hazard_assessment import HazardAssessment
from app.models.time_entry import TimeEntry
from app.models.toolbox_meeting import ToolboxMeeting
from app.services.payroll_readiness_summary import get_payroll_readiness_summary


def get_core_dashboard_overview(*, db: Session, company_id: int) -> dict[str, Any]:
    today = date.today()
    start_today = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)

    active_crews = int(
        db.query(func.count(Crew.crew_id))
        .filter(Crew.company_id == int(company_id), Crew.is_active.is_(True))
        .scalar()
        or 0
    )
    employees_clocked_in = int(
        db.query(func.count(TimeEntry.time_entry_id))
        .filter(TimeEntry.company_id == int(company_id), TimeEntry.status == "active")
        .scalar()
        or 0
    )

    seconds_today = (
        db.query(func.sum(func.extract("epoch", TimeEntry.ended_at - TimeEntry.started_at)))
        .filter(TimeEntry.company_id == int(company_id), TimeEntry.status == "completed", TimeEntry.started_at >= start_today)
        .scalar()
        or 0
    )
    hours_logged_today = round(float(seconds_today) / 3600.0, 2)

    open_jobs = int(
        db.query(func.count(Job.id))
        .filter(Job.company_id == int(company_id), Job.is_active.is_(True))
        .scalar()
        or 0
    )

    payroll_pending = int(
        db.query(func.count(PayrollRun.payroll_run_id))
        .filter(PayrollRun.company_id == int(company_id), PayrollRun.status != "POSTED")
        .scalar()
        or 0
    )

    safety_alerts = int(
        db.query(func.count(FoundationActivityLog.foundation_activity_id))
        .filter(
            FoundationActivityLog.company_id == int(company_id),
            FoundationActivityLog.activity_type == "ISSUE_REPORTED",
            FoundationActivityLog.created_at >= start_today,
        )
        .scalar()
        or 0
    )

    active_member_subq = (
        db.query(
            CrewMember.crew_id.label("crew_id"),
            func.count(CrewMember.crew_member_id).label("active_members"),
        )
        .filter(CrewMember.company_id == int(company_id), CrewMember.removed_at.is_(None))
        .group_by(CrewMember.crew_id)
        .subquery()
    )

    clocked_member_subq = (
        db.query(
            CrewMember.crew_id.label("crew_id"),
            func.count(TimeEntry.time_entry_id).label("clocked_members"),
        )
        .join(
            TimeEntry,
            (TimeEntry.company_id == CrewMember.company_id)
            & (TimeEntry.employee_id == CrewMember.employee_id)
            & (TimeEntry.status == "active"),
        )
        .filter(CrewMember.company_id == int(company_id), CrewMember.removed_at.is_(None))
        .group_by(CrewMember.crew_id)
        .subquery()
    )

    crew_rows = (
        db.query(
            Crew.crew_id,
            Crew.name,
            func.coalesce(active_member_subq.c.active_members, 0),
            func.coalesce(clocked_member_subq.c.clocked_members, 0),
        )
        .outerjoin(active_member_subq, active_member_subq.c.crew_id == Crew.crew_id)
        .outerjoin(clocked_member_subq, clocked_member_subq.c.crew_id == Crew.crew_id)
        .filter(Crew.company_id == int(company_id))
        .order_by(Crew.is_active.desc(), Crew.name.asc())
        .all()
    )

    assignment_rows = (
        db.query(
            Job.id,
            Job.name,
            Job.address_label,
            func.count(CrewAssignment.crew_assignment_id),
        )
        .join(
            CrewAssignment,
            (CrewAssignment.company_id == Job.company_id) & (CrewAssignment.job_id == Job.id),
        )
        .filter(Job.company_id == int(company_id), CrewAssignment.assigned_date == today)
        .group_by(Job.id, Job.name, Job.address_label)
        .order_by(func.count(CrewAssignment.crew_assignment_id).desc(), Job.name.asc())
        .limit(6)
        .all()
    )

    activity_rows = (
        db.query(
            FoundationActivityLog.activity_type,
            func.count(FoundationActivityLog.foundation_activity_id),
        )
        .filter(FoundationActivityLog.company_id == int(company_id), FoundationActivityLog.created_at >= start_today)
        .group_by(FoundationActivityLog.activity_type)
        .order_by(func.count(FoundationActivityLog.foundation_activity_id).desc())
        .all()
    )

    next_day = start_today.replace(hour=23, minute=59, second=59, microsecond=999999)
    today_labor_cost = int(
        db.query(func.coalesce(func.sum(JobCostLedger.total_cost_cents), 0))
        .filter(
            JobCostLedger.company_id == int(company_id),
            JobCostLedger.posting_date >= start_today,
            JobCostLedger.posting_date <= next_day,
        )
        .scalar()
        or 0
    )

    invoice_pending = int(
        db.query(func.count(Invoice.invoice_id))
        .filter(Invoice.company_id == int(company_id), Invoice.status.in_(["DRAFT", "ISSUED"]))
        .scalar()
        or 0
    )
    payroll_readiness_summary = get_payroll_readiness_summary(db=db, company_id=int(company_id))

    return {
        "module_context": "core",
        "kpis": {
            "active_crews": active_crews,
            "employees_clocked_in": employees_clocked_in,
            "hours_logged_today": hours_logged_today,
            "open_jobs": open_jobs,
            "payroll_pending": payroll_pending,
            "safety_alerts": safety_alerts,
        },
        "crew_status": [
            {
                "crew_id": str(row[0]),
                "crew_name": str(row[1]),
                "active_members": int(row[2] or 0),
                "clocked_in_members": int(row[3] or 0),
            }
            for row in crew_rows
        ],
        "active_jobs": [
            {
                "job_id": int(row[0]),
                "job_name": str(row[1]),
                "address_label": row[2],
                "assigned_today": int(row[3] or 0),
            }
            for row in assignment_rows
        ],
        "todays_activity": [
            {"activity_type": str(row[0]), "count": int(row[1])}
            for row in activity_rows
        ],
        "cost_snapshot": {
            "today_labor_cost_cents": today_labor_cost,
            "pending_payroll_runs": payroll_pending,
            "draft_or_issued_invoices": invoice_pending,
        },
        "payroll_invoices_snapshot": {
            "today_labor_cost_cents": today_labor_cost,
            "pending_payroll_runs": payroll_pending,
            "draft_or_issued_invoices": invoice_pending,
        },
        "payroll_readiness_summary": payroll_readiness_summary,
        "replace_value": {
            "replacing_today": [
                "Spreadsheet-based crew rollups",
                "Manual morning call-ins",
                "Payroll prep status guessing",
                "Invoice handoff checklists",
            ]
        },
    }


def get_waste_bins_dashboard_overview(*, db: Session, company_id: int) -> dict[str, Any]:
    today = date.today()

    active_bins_count = int(
        db.query(func.count(BinAsset.bin_asset_id))
        .filter(BinAsset.company_id == int(company_id))
        .filter(BinAsset.status != "OUT_OF_SERVICE")
        .scalar()
        or 0
    )
    active_bin_rows = (
        db.query(BinAsset)
        .filter(BinAsset.company_id == int(company_id))
        .filter(BinAsset.status != "OUT_OF_SERVICE")
        .order_by(BinAsset.bin_number.asc())
        .limit(10)
        .all()
    )

    scheduled_pickups_rows = (
        db.query(BinServiceTicket)
        .filter(BinServiceTicket.company_id == int(company_id))
        .filter(BinServiceTicket.service_type.in_(["PICKUP", "PICKUP_BIN"]))
        .filter(BinServiceTicket.status.in_(["OPEN", "SCHEDULED", "DISPATCHED"]))
        .order_by(BinServiceTicket.scheduled_date.asc().nullsfirst(), BinServiceTicket.created_at.asc())
        .limit(10)
        .all()
    )
    scheduled_pickups_count = int(
        db.query(func.count(BinServiceTicket.bin_service_ticket_id))
        .filter(BinServiceTicket.company_id == int(company_id))
        .filter(BinServiceTicket.service_type.in_(["PICKUP", "PICKUP_BIN"]))
        .filter(BinServiceTicket.status.in_(["OPEN", "SCHEDULED", "DISPATCHED"]))
        .scalar()
        or 0
    )

    dispatch_board_rows = (
        db.query(BinServiceTicket)
        .filter(BinServiceTicket.company_id == int(company_id))
        .filter(BinServiceTicket.status.in_(["SCHEDULED", "DISPATCHED"]))
        .order_by(BinServiceTicket.scheduled_date.asc().nullsfirst(), BinServiceTicket.created_at.asc())
        .limit(10)
        .all()
    )

    service_ticket_counts = {
        str(status): int(count or 0)
        for status, count in (
            db.query(BinServiceTicket.status, func.count(BinServiceTicket.bin_service_ticket_id))
            .filter(BinServiceTicket.company_id == int(company_id))
            .group_by(BinServiceTicket.status)
            .all()
        )
    }

    landfill_rows = (
        db.query(LandfillTrip)
        .filter(LandfillTrip.company_id == int(company_id))
        .order_by(LandfillTrip.completed_at.desc(), LandfillTrip.created_at.desc())
        .limit(10)
        .all()
    )

    asset_status_counts = {
        str(status): int(count or 0)
        for status, count in (
            db.query(BinAsset.status, func.count(BinAsset.bin_asset_id))
            .filter(BinAsset.company_id == int(company_id))
            .group_by(BinAsset.status)
            .all()
        )
    }

    route_activity = {
        "scheduled_today_count": int(
            db.query(func.count(BinServiceTicket.bin_service_ticket_id))
            .filter(BinServiceTicket.company_id == int(company_id))
            .filter(BinServiceTicket.scheduled_date == today)
            .scalar()
            or 0
        ),
        "dispatched_today_count": int(
            db.query(func.count(BinServiceTicket.bin_service_ticket_id))
            .filter(BinServiceTicket.company_id == int(company_id))
            .filter(func.date(BinServiceTicket.dispatched_at) == today)
            .scalar()
            or 0
        ),
        "completed_today_count": int(
            db.query(func.count(BinServiceTicket.bin_service_ticket_id))
            .filter(BinServiceTicket.company_id == int(company_id))
            .filter(func.date(BinServiceTicket.completed_at) == today)
            .scalar()
            or 0
        ),
        "rows": [],
    }

    return {
        "module_context": "waste_bins",
        "active_bins": {
            "count": active_bins_count,
            "rows": [
                {
                    "bin_asset_id": str(row.bin_asset_id),
                    "bin_number": str(row.bin_number),
                    "bin_type": str(row.bin_type),
                    "bin_size": str(row.bin_size),
                    "status": str(row.status),
                    "current_customer_site_id": row.current_customer_site_id,
                    "current_job_purchase_order_id": row.current_job_purchase_order_id,
                }
                for row in active_bin_rows
            ],
        },
        "scheduled_pickups": {
            "count": scheduled_pickups_count,
            "rows": [
                {
                    "bin_service_ticket_id": str(row.bin_service_ticket_id),
                    "service_type": str(row.service_type),
                    "status": str(row.status),
                    "scheduled_date": None if row.scheduled_date is None else row.scheduled_date.isoformat(),
                    "scheduled_time_window": row.scheduled_time_window,
                    "assigned_employee_id": row.assigned_employee_id,
                    "assigned_vehicle_label": row.assigned_vehicle_label,
                }
                for row in scheduled_pickups_rows
            ],
        },
        "dispatch_board": {
            "rows": [
                {
                    "bin_service_ticket_id": str(row.bin_service_ticket_id),
                    "service_type": str(row.service_type),
                    "status": str(row.status),
                    "scheduled_date": None if row.scheduled_date is None else row.scheduled_date.isoformat(),
                    "scheduled_time_window": row.scheduled_time_window,
                    "assigned_employee_id": row.assigned_employee_id,
                    "assigned_vehicle_label": row.assigned_vehicle_label,
                    "assigned_bin_asset_id": row.assigned_bin_asset_id,
                }
                for row in dispatch_board_rows
            ],
        },
        "service_tickets": {
            "counts_by_status": {
                "OPEN": int(service_ticket_counts.get("OPEN", 0)),
                "SCHEDULED": int(service_ticket_counts.get("SCHEDULED", 0)),
                "DISPATCHED": int(service_ticket_counts.get("DISPATCHED", 0)),
                "COMPLETED": int(service_ticket_counts.get("COMPLETED", 0)),
                "CANCELLED": int(service_ticket_counts.get("CANCELLED", 0)),
            },
            "open_request_count": int(
                db.query(func.count(BinServiceRequest.bin_service_request_id))
                .filter(BinServiceRequest.company_id == int(company_id))
                .filter(BinServiceRequest.status == "OPEN")
                .scalar()
                or 0
            ),
        },
        "landfill_runs": {
            "rows": [
                {
                    "landfill_trip_id": str(row.landfill_trip_id),
                    "bin_service_ticket_id": str(row.bin_service_ticket_id),
                    "bin_asset_id": str(row.bin_asset_id),
                    "dump_site_name": str(row.dump_site_name),
                    "dump_cost_cents": int(row.dump_cost_cents),
                    "completed_at": row.completed_at.isoformat(),
                }
                for row in landfill_rows
            ],
        },
        "asset_status": {
            "counts_by_status": {
                "AVAILABLE": int(asset_status_counts.get("AVAILABLE", 0)),
                "ASSIGNED": int(asset_status_counts.get("ASSIGNED", 0)),
                "OUT_OF_SERVICE": int(asset_status_counts.get("OUT_OF_SERVICE", 0)),
            },
        },
        "route_activity": route_activity,
    }


def get_foundations_dashboard_overview(*, db: Session, company_id: int) -> dict[str, Any]:
    hazard_photo_counts = (
        db.query(
            JobDocument.hazard_assessment_id.label("hazard_assessment_id"),
            func.count(JobDocument.job_document_id).label("issue_photo_count"),
        )
        .filter(
            JobDocument.company_id == int(company_id),
            JobDocument.document_type == "ISSUE_PHOTO",
            JobDocument.hazard_assessment_id.isnot(None),
        )
        .group_by(JobDocument.hazard_assessment_id)
        .subquery()
    )

    recent_hazard_rows = (
        db.query(
            HazardAssessment.hazard_assessment_id,
            HazardAssessment.job_id,
            Job.name,
            HazardAssessment.scope_id,
            HazardAssessment.assessment_date,
            HazardAssessment.created_at,
            func.coalesce(hazard_photo_counts.c.issue_photo_count, 0),
        )
        .join(Job, (Job.company_id == HazardAssessment.company_id) & (Job.id == HazardAssessment.job_id))
        .outerjoin(
            hazard_photo_counts,
            hazard_photo_counts.c.hazard_assessment_id == HazardAssessment.hazard_assessment_id,
        )
        .filter(HazardAssessment.company_id == int(company_id))
        .order_by(HazardAssessment.created_at.desc(), HazardAssessment.hazard_assessment_id.asc())
        .limit(10)
        .all()
    )

    recent_toolbox_rows = (
        db.query(
            ToolboxMeeting.toolbox_meeting_id,
            ToolboxMeeting.job_id,
            Job.name,
            ToolboxMeeting.scope_id,
            ToolboxMeeting.meeting_date,
            ToolboxMeeting.attendee_count,
            ToolboxMeeting.created_at,
        )
        .outerjoin(Job, (Job.company_id == ToolboxMeeting.company_id) & (Job.id == ToolboxMeeting.job_id))
        .filter(ToolboxMeeting.company_id == int(company_id))
        .order_by(ToolboxMeeting.created_at.desc(), ToolboxMeeting.toolbox_meeting_id.asc())
        .limit(10)
        .all()
    )
    toolbox_meeting_count = int(
        db.query(func.count(ToolboxMeeting.toolbox_meeting_id))
        .filter(ToolboxMeeting.company_id == int(company_id))
        .scalar()
        or 0
    )
    toolbox_attendee_total = (
        db.query(func.sum(ToolboxMeeting.attendee_count))
        .filter(ToolboxMeeting.company_id == int(company_id), ToolboxMeeting.attendee_count.isnot(None))
        .scalar()
    )
    toolbox_attendance_meeting_count = int(
        db.query(func.count(ToolboxMeeting.toolbox_meeting_id))
        .filter(ToolboxMeeting.company_id == int(company_id), ToolboxMeeting.attendee_count.isnot(None))
        .scalar()
        or 0
    )

    recent_blueprint_delivery_rows = (
        db.query(
            JobDocumentDelivery.job_document_delivery_id,
            JobDocumentDelivery.job_document_id,
            JobDocument.job_id,
            Job.name,
            JobDocument.scope_id,
            JobDocument.file_name,
            JobDocument.document_type,
            JobDocumentDelivery.employee_id,
            JobDocumentDelivery.delivered_at,
            JobDocumentDelivery.viewed_at,
        )
        .join(
            JobDocument,
            (JobDocument.company_id == JobDocumentDelivery.company_id)
            & (JobDocument.job_document_id == JobDocumentDelivery.job_document_id),
        )
        .outerjoin(Job, (Job.company_id == JobDocument.company_id) & (Job.id == JobDocument.job_id))
        .filter(
            JobDocumentDelivery.company_id == int(company_id),
            JobDocument.document_type == "BLUEPRINT",
        )
        .order_by(JobDocumentDelivery.delivered_at.desc(), JobDocumentDelivery.job_document_delivery_id.asc())
        .limit(10)
        .all()
    )
    pending_blueprint_acknowledgement_count = int(
        db.query(func.count(JobDocumentDelivery.job_document_delivery_id))
        .join(
            JobDocument,
            (JobDocument.company_id == JobDocumentDelivery.company_id)
            & (JobDocument.job_document_id == JobDocumentDelivery.job_document_id),
        )
        .filter(
            JobDocumentDelivery.company_id == int(company_id),
            JobDocument.document_type == "BLUEPRINT",
            JobDocumentDelivery.viewed_at.is_(None),
        )
        .scalar()
        or 0
    )

    recent_message_rows = (
        db.query(
            FoundationsMessage.foundations_message_id,
            FoundationsMessage.job_id,
            Job.name,
            FoundationsMessage.scope_id,
            FoundationsMessage.employee_id,
            FoundationsMessage.message_type,
            FoundationsMessage.subject,
            FoundationsMessage.created_at,
        )
        .outerjoin(Job, (Job.company_id == FoundationsMessage.company_id) & (Job.id == FoundationsMessage.job_id))
        .filter(FoundationsMessage.company_id == int(company_id))
        .order_by(FoundationsMessage.created_at.desc(), FoundationsMessage.foundations_message_id.asc())
        .limit(10)
        .all()
    )

    recent_issue_rows = (
        db.query(
            FoundationActivityLog.foundation_activity_id,
            FoundationActivityLog.job_id,
            Job.name,
            FoundationActivityLog.scope_id,
            FoundationActivityLog.employee_id,
            FoundationActivityLog.activity_type,
            FoundationActivityLog.notes,
            FoundationActivityLog.created_at,
        )
        .join(Job, (Job.company_id == FoundationActivityLog.company_id) & (Job.id == FoundationActivityLog.job_id))
        .filter(
            FoundationActivityLog.company_id == int(company_id),
            FoundationActivityLog.activity_type == "ISSUE_REPORTED",
        )
        .order_by(FoundationActivityLog.created_at.desc(), FoundationActivityLog.foundation_activity_id.asc())
        .limit(10)
        .all()
    )
    blocker_count = int(
        db.query(func.count(FoundationActivityLog.foundation_activity_id))
        .filter(
            FoundationActivityLog.company_id == int(company_id),
            FoundationActivityLog.activity_type == "ISSUE_REPORTED",
        )
        .scalar()
        or 0
    )

    attendance_summary: dict[str, Any] | None
    if toolbox_meeting_count == 0:
        attendance_summary = None
    else:
        attendance_summary = {
            "meeting_count": toolbox_meeting_count,
            "meetings_with_attendee_count": toolbox_attendance_meeting_count,
            "attendee_total": None if toolbox_attendee_total is None else int(toolbox_attendee_total),
            "attendee_average": (
                None
                if not toolbox_attendance_meeting_count or toolbox_attendee_total is None
                else round(float(toolbox_attendee_total) / float(toolbox_attendance_meeting_count), 2)
            ),
        }

    return {
        "module_context": "foundations",
        "hazard_assessments": {
            "open_count": None,
            "needs_review_count": None,
            "recent_rows": [
                {
                    "hazard_assessment_id": str(row[0]),
                    "job_id": int(row[1]),
                    "job_name": str(row[2]),
                    "scope_id": None if row[3] is None else int(row[3]),
                    "assessment_date": row[4],
                    "created_at": row[5],
                    "issue_photo_count": int(row[6] or 0),
                }
                for row in recent_hazard_rows
            ],
        },
        "toolbox_meetings": {
            "recent_rows": [
                {
                    "toolbox_meeting_id": str(row[0]),
                    "job_id": None if row[1] is None else int(row[1]),
                    "job_name": row[2],
                    "scope_id": None if row[3] is None else int(row[3]),
                    "meeting_date": row[4],
                    "attendee_count": None if row[5] is None else int(row[5]),
                    "created_at": row[6],
                }
                for row in recent_toolbox_rows
            ],
            "attendance_summary": attendance_summary,
            "compliance_summary": None,
        },
        "blueprint_delivery": {
            "recent_rows": [
                {
                    "job_document_delivery_id": str(row[0]),
                    "job_document_id": str(row[1]),
                    "job_id": None if row[2] is None else int(row[2]),
                    "job_name": row[3],
                    "scope_id": None if row[4] is None else int(row[4]),
                    "file_name": str(row[5]),
                    "document_type": str(row[6]),
                    "employee_id": int(row[7]),
                    "delivered_at": row[8],
                    "viewed_at": row[9],
                }
                for row in recent_blueprint_delivery_rows
            ],
            "pending_acknowledgement_count": pending_blueprint_acknowledgement_count,
        },
        "job_communication": {
            "recent_rows": [
                {
                    "foundations_message_id": str(row[0]),
                    "job_id": None if row[1] is None else int(row[1]),
                    "job_name": row[2],
                    "scope_id": None if row[3] is None else int(row[3]),
                    "employee_id": None if row[4] is None else int(row[4]),
                    "message_type": str(row[5]),
                    "subject": row[6],
                    "created_at": row[7],
                }
                for row in recent_message_rows
            ],
            "unresolved_thread_count": None,
        },
        "progress_issues": {
            "recent_rows": [
                {
                    "foundation_activity_id": str(row[0]),
                    "job_id": int(row[1]),
                    "job_name": str(row[2]),
                    "scope_id": int(row[3]),
                    "employee_id": int(row[4]),
                    "activity_type": str(row[5]),
                    "notes": row[6],
                    "created_at": row[7],
                }
                for row in recent_issue_rows
            ],
            "blocker_count": blocker_count,
        },
    }

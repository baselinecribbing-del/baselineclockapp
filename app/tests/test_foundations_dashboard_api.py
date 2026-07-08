from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.foundation_activity_log import FoundationActivityLog
from app.models.foundations_message import FoundationsMessage
from app.models.hazard_assessment import HazardAssessment
from app.models.job import Job
from app.models.job_document import JobDocument
from app.models.job_document_delivery import JobDocumentDelivery
from app.models.scope import Scope
from app.models.toolbox_meeting import ToolboxMeeting

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "foundations-dashboard-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _seed_foundations_dashboard_data(company_id: int, suffix: str) -> dict[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)

    db = SessionLocal()
    try:
        employee = Employee(company_id=company_id, name=f"Foundations Worker {suffix}", is_active=True, hourly_rate_cents=3200)
        db.add(employee)
        db.flush()

        job = Job(company_id=company_id, name=f"Foundations Job {suffix}", is_active=True)
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Footings {suffix}", is_active=True)
        db.add(scope)
        db.flush()

        hazard_old = HazardAssessment(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            completed_by_employee_id=employee.id,
            assessment_date=date(2026, 3, 9),
            form_payload={"hazard": "rebar"},
            created_at=now - timedelta(hours=5),
        )
        hazard_new = HazardAssessment(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            completed_by_employee_id=employee.id,
            assessment_date=date(2026, 3, 10),
            form_payload={"hazard": "slip risk"},
            created_at=now - timedelta(hours=1),
        )
        db.add_all([hazard_old, hazard_new])
        db.flush()

        issue_photo = JobDocument(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            hazard_assessment_id=str(hazard_new.hazard_assessment_id),
            document_type="ISSUE_PHOTO",
            file_name=f"hazard-{suffix}.jpg",
            storage_key=f"hazards/{suffix}.jpg",
            created_at=now - timedelta(minutes=55),
        )

        toolbox_old = ToolboxMeeting(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            meeting_date=date(2026, 3, 9),
            completed_by_employee_id=employee.id,
            attendee_count=5,
            form_payload={"topic": "prep"},
            created_at=now - timedelta(hours=4),
        )
        toolbox_new = ToolboxMeeting(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            meeting_date=date(2026, 3, 10),
            completed_by_employee_id=employee.id,
            attendee_count=7,
            form_payload={"topic": "pour"},
            created_at=now - timedelta(minutes=45),
        )

        blueprint_old = JobDocument(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            document_type="BLUEPRINT",
            file_name=f"blueprint-old-{suffix}.pdf",
            storage_key=f"blueprints/{suffix}-old.pdf",
            created_at=now - timedelta(days=1),
        )
        blueprint_new = JobDocument(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            document_type="BLUEPRINT",
            file_name=f"blueprint-new-{suffix}.pdf",
            storage_key=f"blueprints/{suffix}-new.pdf",
            created_at=now - timedelta(hours=2),
        )
        db.add_all([issue_photo, toolbox_old, toolbox_new, blueprint_old, blueprint_new])
        db.flush()

        delivery_old = JobDocumentDelivery(
            company_id=company_id,
            job_document_id=str(blueprint_old.job_document_id),
            employee_id=employee.id,
            delivered_at=now - timedelta(hours=3),
            viewed_at=now - timedelta(hours=2, minutes=30),
        )
        delivery_new = JobDocumentDelivery(
            company_id=company_id,
            job_document_id=str(blueprint_new.job_document_id),
            employee_id=employee.id,
            delivered_at=now - timedelta(minutes=30),
            viewed_at=None,
        )

        message_old = FoundationsMessage(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            employee_id=employee.id,
            message_type="JOB_INSTRUCTION",
            subject=f"Sequence {suffix} old",
            body="Start north edge",
            created_by_user_id="super-old",
            created_at=now - timedelta(hours=6),
        )
        message_new = FoundationsMessage(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            employee_id=employee.id,
            message_type="SAFETY_NOTICE",
            subject=f"Sequence {suffix} new",
            body="Pump truck delayed",
            created_by_user_id="super-new",
            created_at=now - timedelta(minutes=20),
        )

        issue_old = FoundationActivityLog(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            employee_id=employee.id,
            activity_type="ISSUE_REPORTED",
            notes="Old blocker",
            photo_url=None,
            created_at=now - timedelta(hours=7),
        )
        issue_new = FoundationActivityLog(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            employee_id=employee.id,
            activity_type="ISSUE_REPORTED",
            notes="Fresh blocker",
            photo_url=None,
            created_at=now - timedelta(minutes=10),
        )

        db.add_all([delivery_old, delivery_new, message_old, message_new, issue_old, issue_new])
        db.commit()

        return {
            "job_name": str(job.name),
            "latest_hazard_id": str(hazard_new.hazard_assessment_id),
            "latest_toolbox_id": str(toolbox_new.toolbox_meeting_id),
            "latest_delivery_id": str(delivery_new.job_document_delivery_id),
            "latest_message_id": str(message_new.foundations_message_id),
            "latest_issue_id": str(issue_new.foundation_activity_id),
        }
    finally:
        db.close()


def test_foundations_dashboard_returns_real_sections():
    company_id = 53001
    seeded = _seed_foundations_dashboard_data(company_id, "real")

    resp = client.get(
        "/command-center/overview",
        headers=_auth_headers(company_id),
        params={"module_context": "foundations"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["module_context"] == "foundations"
    assert "hazard_assessments" in body
    assert "toolbox_meetings" in body
    assert "blueprint_delivery" in body
    assert "job_communication" in body
    assert "progress_issues" in body

    assert body["hazard_assessments"]["open_count"] is None
    assert body["hazard_assessments"]["needs_review_count"] is None
    assert body["hazard_assessments"]["recent_rows"][0]["hazard_assessment_id"] == seeded["latest_hazard_id"]
    assert body["hazard_assessments"]["recent_rows"][0]["issue_photo_count"] == 1

    assert body["toolbox_meetings"]["attendance_summary"]["meeting_count"] == 2
    assert body["toolbox_meetings"]["attendance_summary"]["attendee_total"] == 12
    assert body["toolbox_meetings"]["attendance_summary"]["attendee_average"] == 6.0
    assert body["toolbox_meetings"]["compliance_summary"] is None

    assert body["blueprint_delivery"]["pending_acknowledgement_count"] == 1
    assert body["blueprint_delivery"]["recent_rows"][0]["job_document_delivery_id"] == seeded["latest_delivery_id"]

    assert body["job_communication"]["recent_rows"][0]["foundations_message_id"] == seeded["latest_message_id"]
    assert body["job_communication"]["unresolved_thread_count"] is None

    assert body["progress_issues"]["blocker_count"] == 2
    assert body["progress_issues"]["recent_rows"][0]["foundation_activity_id"] == seeded["latest_issue_id"]


def test_foundations_dashboard_company_isolation():
    owner_company_id = 53002
    other_company_id = 53003
    _seed_foundations_dashboard_data(owner_company_id, "scope")

    other = client.get(
        "/command-center/overview",
        headers=_auth_headers(other_company_id),
        params={"module_context": "foundations"},
    )
    assert other.status_code == 200, other.text
    body = other.json()

    assert body["hazard_assessments"]["recent_rows"] == []
    assert body["toolbox_meetings"]["recent_rows"] == []
    assert body["blueprint_delivery"]["recent_rows"] == []
    assert body["job_communication"]["recent_rows"] == []
    assert body["progress_issues"]["recent_rows"] == []
    assert body["blueprint_delivery"]["pending_acknowledgement_count"] == 0
    assert body["progress_issues"]["blocker_count"] == 0


def test_foundations_dashboard_empty_state_is_honest():
    company_id = 53004

    resp = client.get(
        "/command-center/overview",
        headers=_auth_headers(company_id),
        params={"module_context": "foundations"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["hazard_assessments"] == {
        "open_count": None,
        "needs_review_count": None,
        "recent_rows": [],
    }
    assert body["toolbox_meetings"] == {
        "recent_rows": [],
        "attendance_summary": None,
        "compliance_summary": None,
    }
    assert body["blueprint_delivery"] == {
        "recent_rows": [],
        "pending_acknowledgement_count": 0,
    }
    assert body["job_communication"] == {
        "recent_rows": [],
        "unresolved_thread_count": None,
    }
    assert body["progress_issues"] == {
        "recent_rows": [],
        "blocker_count": 0,
    }


def test_foundations_dashboard_returns_recent_rows_where_data_exists():
    company_id = 53005
    seeded = _seed_foundations_dashboard_data(company_id, "recent")

    resp = client.get(
        "/command-center/overview",
        headers=_auth_headers(company_id),
        params={"module_context": "foundations"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["hazard_assessments"]["recent_rows"][0]["hazard_assessment_id"] == seeded["latest_hazard_id"]
    assert body["toolbox_meetings"]["recent_rows"][0]["toolbox_meeting_id"] == seeded["latest_toolbox_id"]
    assert body["blueprint_delivery"]["recent_rows"][0]["job_document_delivery_id"] == seeded["latest_delivery_id"]
    assert body["job_communication"]["recent_rows"][0]["foundations_message_id"] == seeded["latest_message_id"]
    assert body["progress_issues"]["recent_rows"][0]["foundation_activity_id"] == seeded["latest_issue_id"]
    assert body["progress_issues"]["recent_rows"][0]["job_name"] == seeded["job_name"]

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.crew import Crew
from app.models.crew_assignment import CrewAssignment
from app.models.crew_member import CrewMember
from app.models.employee import Employee
from app.models.foundation_activity_log import FoundationActivityLog
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.pay_period import PayPeriod
from app.models.payroll_run import PayrollRun
from app.models.scope import Scope
from app.models.time_entry import TimeEntry

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _seed_company_data(company_id: int):
    now = datetime.now(timezone.utc)
    today = date.today()

    db = SessionLocal()
    try:
        e1 = Employee(company_id=company_id, name="Worker A", legal_name="Worker A", is_active=True)
        e2 = Employee(company_id=company_id, name="Worker B", legal_name="Worker B", is_active=True)
        db.add_all([e1, e2])
        db.flush()

        j1 = Job(company_id=company_id, name="Job One", address_label="10 Main St", is_active=True)
        j2 = Job(company_id=company_id, name="Job Two", address_label="22 Yard Rd", is_active=True)
        db.add_all([j1, j2])
        db.flush()
        s1 = Scope(company_id=company_id, job_id=j1.id, name="Scope One", is_active=True)
        s2 = Scope(company_id=company_id, job_id=j2.id, name="Scope Two", is_active=True)
        db.add_all([s1, s2])
        db.flush()

        crew = Crew(company_id=company_id, name="Crew Prime", supervisor_employee_id=e1.id, is_active=True)
        db.add(crew)
        db.flush()

        db.add_all([
            CrewMember(company_id=company_id, crew_id=crew.crew_id, employee_id=e1.id),
            CrewMember(company_id=company_id, crew_id=crew.crew_id, employee_id=e2.id),
        ])

        db.add_all([
            CrewAssignment(
                company_id=company_id,
                employee_id=e1.id,
                job_id=j1.id,
                scope_id=s1.id,
                assigned_date=today,
                assigned_by_user_id="mgr",
                assignment_notes="Morning shift",
                status="ASSIGNED",
            ),
            CrewAssignment(
                company_id=company_id,
                employee_id=e2.id,
                job_id=j2.id,
                scope_id=s2.id,
                assigned_date=today,
                assigned_by_user_id="mgr",
                assignment_notes="Afternoon shift",
                status="ASSIGNED",
            ),
        ])

        db.add(
            TimeEntry(
                time_entry_id=f"te-active-{company_id}",
                company_id=company_id,
                employee_id=e1.id,
                job_id=j1.id,
                scope_id=s1.id,
                started_at=now - timedelta(hours=2),
                ended_at=None,
                status="active",
                approval_status="pending",
            )
        )
        db.add(
            TimeEntry(
                time_entry_id=f"te-complete-{company_id}",
                company_id=company_id,
                employee_id=e2.id,
                job_id=j2.id,
                scope_id=s2.id,
                started_at=now - timedelta(hours=5),
                ended_at=now - timedelta(hours=1),
                status="completed",
                approval_status="approved",
            )
        )

        db.add(
            FoundationActivityLog(
                company_id=company_id,
                job_id=j1.id,
                scope_id=s1.id,
                employee_id=e1.id,
                activity_type="ISSUE_REPORTED",
                notes="Access blocked",
                photo_url=None,
            )
        )

        db.add(
            JobCostLedger(
                company_id=company_id,
                job_id=j1.id,
                scope_id=s1.id,
                employee_id=e1.id,
                source_type="LABOR",
                source_reference_id=f"seed-labor-{company_id}",
                cost_category="LABOR_DIRECT",
                quantity=1,
                unit_cost_cents=25000,
                total_cost_cents=25000,
                cost_source="MANUAL",
                posting_date=now,
            )
        )

        db.add(
            PayPeriod(
                pay_period_id=f"pp-{company_id}",
                company_id=company_id,
                start_date=today - timedelta(days=7),
                end_date=today + timedelta(days=7),
                status="OPEN",
            )
        )
        db.add(
            PayrollRun(
                company_id=company_id,
                pay_period_id=f"pp-{company_id}",
                status="DRAFT",
            )
        )

        db.commit()
        return {"crew_id": crew.crew_id, "job_id": j1.id}
    finally:
        db.close()


def test_command_center_overview_returns_expected_sections():
    company_id = 52001
    _seed_company_data(company_id)

    res = client.get("/command-center/overview", headers=_auth_headers(company_id))
    assert res.status_code == 200, res.text
    body = res.json()

    assert "kpis" in body
    assert "crew_status" in body
    assert "active_jobs" in body
    assert "todays_activity" in body
    assert "cost_snapshot" in body
    assert "payroll_invoices_snapshot" in body
    assert "payroll_readiness_summary" in body
    assert "replace_value" in body

    assert body["kpis"]["active_crews"] >= 1
    assert body["kpis"]["employees_clocked_in"] >= 1
    assert body["kpis"]["hours_logged_today"] >= 0
    assert body["kpis"]["payroll_pending"] >= 1
    assert body["payroll_readiness_summary"]["pending_time_approvals_count"] == 0
    assert body["payroll_readiness_summary"]["rejected_time_entries_count"] == 0
    assert body["payroll_readiness_summary"]["employees_not_payroll_ready_count"] == 2
    assert body["payroll_readiness_summary"]["employees_missing_tax_setup_count"] == 2
    assert body["payroll_readiness_summary"]["employees_missing_payment_method_count"] == 2
    assert body["payroll_readiness_summary"]["approved_hours_ready_count"] == 4.0


def test_field_crew_board_filters_and_company_scoping():
    c1 = 52002
    c2 = 52003
    seeded = _seed_company_data(c1)

    list_res = client.get("/field/crew-board", headers=_auth_headers(c1))
    assert list_res.status_code == 200, list_res.text
    rows = list_res.json()["rows"]
    assert len(rows) >= 2
    assert any(row["status"] == "CLOCKED_IN" for row in rows)

    by_crew = client.get(f"/field/crew-board?crew_id={seeded['crew_id']}", headers=_auth_headers(c1))
    assert by_crew.status_code == 200
    assert len(by_crew.json()["rows"]) >= 1

    by_job = client.get(f"/field/crew-board?job_id={seeded['job_id']}", headers=_auth_headers(c1))
    assert by_job.status_code == 200
    assert len(by_job.json()["rows"]) >= 1

    by_status = client.get("/field/crew-board?status=CLOCKED_IN", headers=_auth_headers(c1))
    assert by_status.status_code == 200
    assert all(row["status"] == "CLOCKED_IN" for row in by_status.json()["rows"])

    isolated = client.get("/field/crew-board", headers=_auth_headers(c2))
    assert isolated.status_code == 200
    assert isolated.json()["rows"] == []

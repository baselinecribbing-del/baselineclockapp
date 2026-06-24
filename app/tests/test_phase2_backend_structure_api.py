from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.landfill_trip import LandfillTrip
from app.models.pay_period import PayPeriod
from app.models.scope import Scope
from app.models.time_entry import TimeEntry

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "phase2-test", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_job_po(company_id: int, suffix: str) -> str:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"Phase2 Job {suffix}", is_active=True)
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Phase2 Scope {suffix}", is_active=True)
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-PHASE2-{suffix}",
            status="ISSUED",
        )
        db.add(po)
        db.commit()
        return str(po.job_purchase_order_id)
    finally:
        db.close()


def _seed_payroll_period_employee_and_time_entry(company_id: int, suffix: str) -> tuple[str, int]:
    today = date.today()
    started_at = datetime.now(timezone.utc) - timedelta(hours=8)
    ended_at = started_at + timedelta(hours=4)

    db = SessionLocal()
    try:
        pay_period = PayPeriod(
            pay_period_id=f"pp-phase2-{suffix}",
            company_id=company_id,
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
            status="OPEN",
        )
        db.add(pay_period)

        job = Job(company_id=company_id, name=f"Payroll Job {suffix}", is_active=True)
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Payroll Scope {suffix}", is_active=True)
        db.add(scope)
        db.flush()

        employee = Employee(
            company_id=company_id,
            name=f"Payroll Employee {suffix}",
            legal_name=f"Payroll Employee {suffix}",
            is_active=True,
            requires_payroll=True,
            hourly_rate_cents=3000,
            payment_method="DIRECT_DEPOSIT",
            country="CA",
            province="AB",
            province_of_employment="AB",
            federal_claim_amount=150,
        )
        db.add(employee)
        db.flush()

        db.add(
            TimeEntry(
                time_entry_id=f"te-phase2-{suffix}",
                company_id=company_id,
                employee_id=employee.id,
                job_id=job.id,
                scope_id=scope.id,
                started_at=started_at,
                ended_at=ended_at,
                status="completed",
                approval_status="approved",
            )
        )
        db.commit()
        return str(pay_period.pay_period_id), int(employee.id)
    finally:
        db.close()


def _seed_employee(company_id: int, suffix: str) -> int:
    db = SessionLocal()
    try:
        employee = Employee(
            company_id=company_id,
            name=f"Employee {suffix}",
            legal_name=f"Employee {suffix}",
            country="CA",
            province="AB",
            province_of_employment="AB",
            federal_claim_amount=100,
            is_active=True,
        )
        db.add(employee)
        db.commit()
        return int(employee.id)
    finally:
        db.close()


def test_command_center_supports_core_and_waste_bins_contexts():
    core_company_id = 53001
    core_resp = client.get("/command-center/overview", headers=_auth_headers(core_company_id))
    assert core_resp.status_code == 200, core_resp.text
    core_body = core_resp.json()
    assert core_body["module_context"] == "core"
    assert "kpis" in core_body
    assert "payroll_readiness_summary" in core_body

    waste_company_id = 53002
    po_id = _seed_job_po(waste_company_id, "WB")

    site = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(waste_company_id),
        json={
            "customer_name": "Waste Builder",
            "site_name": "North Yard",
            "address_line_1": "100 Haul Rd",
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T1A1A1",
        },
    )
    assert site.status_code == 200, site.text
    site_id = str(site.json()["customer_site_id"])

    request_resp = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(waste_company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": "PICKUP",
            "request_notes": "Need a pickup",
        },
    )
    assert request_resp.status_code == 200, request_resp.text
    request_id = str(request_resp.json()["bin_service_request_id"])

    ticket_resp = client.post(
        "/waste-bin/service-tickets",
        headers=_auth_headers(waste_company_id),
        json={
            "bin_service_request_id": request_id,
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "service_type": "PICKUP_BIN",
            "status": "OPEN",
        },
    )
    assert ticket_resp.status_code == 200, ticket_resp.text
    ticket_id = str(ticket_resp.json()["bin_service_ticket_id"])

    scheduled = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/schedule",
        headers=_auth_headers(waste_company_id),
        json={"scheduled_date": date.today().isoformat(), "scheduled_time_window": "08:00-10:00"},
    )
    assert scheduled.status_code == 200, scheduled.text

    asset = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(waste_company_id),
        json={
            "bin_number": "PHASE2-BIN-1",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
            "current_customer_site_id": site_id,
            "current_job_purchase_order_id": po_id,
        },
    )
    assert asset.status_code == 200, asset.text
    asset_id = str(asset.json()["bin_asset_id"])

    db = SessionLocal()
    try:
        db.add(
            LandfillTrip(
                company_id=waste_company_id,
                bin_service_ticket_id=ticket_id,
                bin_asset_id=asset_id,
                dump_site_name="City Landfill",
                dump_cost_cents=12500,
                km_driven=18.5,
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    finally:
        db.close()

    waste_resp = client.get(
        "/command-center/overview?module_context=waste_bins",
        headers=_auth_headers(waste_company_id),
    )
    assert waste_resp.status_code == 200, waste_resp.text
    body = waste_resp.json()
    assert body["module_context"] == "waste_bins"
    assert body["active_bins"]["count"] == 1
    assert body["scheduled_pickups"]["count"] == 1
    assert body["dispatch_board"]["rows"] != []
    assert body["service_tickets"]["counts_by_status"]["SCHEDULED"] == 1
    assert len(body["landfill_runs"]["rows"]) == 1
    assert body["asset_status"]["counts_by_status"]["AVAILABLE"] == 1
    assert "scheduled_today_count" in body["route_activity"]


def test_payroll_processing_overview_supports_approved_hours_review_before_run_creation():
    company_id = 53003
    pay_period_id, employee_id = _seed_payroll_period_employee_and_time_entry(company_id, "pre")

    resp = client.get(
        f"/payroll/processing/overview?pay_period_id={pay_period_id}",
        headers=_auth_headers(company_id),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["pay_period"]["pay_period_id"] == pay_period_id
    assert body["run_creation"]["can_create_payroll_run"] is True
    assert body["run_execution"]["payroll_run"] is None
    assert body["approved_hours_review"]["total_approved_hours"] == 4.0
    assert body["approved_hours_review"]["rows"][0]["employee_id"] == employee_id
    assert body["approved_hours_review"]["rows"][0]["approved_entry_count"] == 1
    assert body["pay_employees"]["rows"] == []
    assert body["pay_employees"]["total_net_payroll_cents"] is None


def test_payroll_processing_and_source_deductions_use_real_run_data_and_honest_placeholders():
    company_id = 53004
    pay_period_id, employee_id = _seed_payroll_period_employee_and_time_entry(company_id, "run")

    create_run = client.post(
        "/payroll/runs",
        headers=_auth_headers(company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert create_run.status_code == 200, create_run.text
    payroll_run_id = str(create_run.json()["payroll_run_id"])
    assert create_run.json()["items_created"] == 1

    finalize = client.post(f"/payroll/runs/{payroll_run_id}/finalize", headers=_auth_headers(company_id))
    assert finalize.status_code == 200, finalize.text
    assert finalize.json()["paystubs"]["generated"] == 1
    assert finalize.json()["deductions"]["generated"] == 2

    paystubs = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert paystubs.status_code == 200, paystubs.text
    assert paystubs.json()["generated"] == 0

    deductions = client.post(
        f"/payroll/runs/{payroll_run_id}/deductions/generate",
        headers=_auth_headers(company_id),
    )
    assert deductions.status_code == 200, deductions.text
    assert deductions.json()["generated"] == 0

    processing = client.get(
        f"/payroll/processing/overview?payroll_run_id={payroll_run_id}",
        headers=_auth_headers(company_id),
    )
    assert processing.status_code == 200, processing.text
    body = processing.json()
    assert body["run_execution"]["payroll_run"]["payroll_run_id"] == payroll_run_id
    assert body["run_execution"]["approval_state"]["payroll_run_status"] == "FINALIZED"
    assert body["approved_hours_review"]["rows"][0]["employee_id"] == employee_id
    assert body["pay_employees"]["deductions_ready"] is True
    assert body["pay_employees"]["rows"][0]["gross_pay_cents"] == 12000
    assert body["pay_employees"]["rows"][0]["deductions_cents"] == 960
    assert body["pay_employees"]["rows"][0]["net_pay_cents"] == 11040
    assert body["pay_employees"]["rows"][0]["payment_method"] == "DIRECT_DEPOSIT"
    assert body["pay_employees"]["total_net_payroll_cents"] == 11040

    source_deductions = client.get(
        f"/payroll/runs/{payroll_run_id}/source-deductions",
        headers=_auth_headers(company_id),
    )
    assert source_deductions.status_code == 200, source_deductions.text
    deductions_body = source_deductions.json()
    assert deductions_body["components"]["cpp_employee"] == {"amount_cents": 720, "available": True}
    assert deductions_body["components"]["ei_employee"] == {"amount_cents": 240, "available": True}
    assert deductions_body["components"]["cpp_employer"] == {"amount_cents": None, "available": False}
    assert deductions_body["components"]["federal_tax"] == {"amount_cents": None, "available": False}
    assert deductions_body["remittance_totals"]["employee_portions_cents"] == 960
    assert deductions_body["remittance_totals"]["total_cents"] is None
    assert deductions_body["due_date"] is None
    assert deductions_body["remittance_status"] == "UNAVAILABLE"


def test_employee_tax_configuration_preset_endpoint_returns_country_province_metadata():
    company_id = 53005
    employee_id = _seed_employee(company_id, "tax")

    resp = client.get(
        f"/employees/{employee_id}/tax-configuration-preset",
        headers=_auth_headers(company_id),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["employee_id"] == employee_id
    assert body["country"] == "CA"
    assert body["province_state"] == "AB"
    assert body["preset_code"] == "CA-AB-PAYROLL-BASE"
    assert body["tax_authority"] == "CRA"
    assert body["calculation_engine_status"] == "NOT_IMPLEMENTED"
    assert body["metadata"]["supports_source_deductions_tracking"] is True
    assert "province_of_employment" in body["metadata"]["supported_employee_fields"]

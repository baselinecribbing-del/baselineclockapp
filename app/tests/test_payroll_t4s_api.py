from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.company_profile import CompanyProfile
from app.models.employee import Employee
from app.models.event_outbox import EventOutbox
from app.models.pay_period import PayPeriod
from app.models.payroll_deduction import PayrollDeduction
from app.models.payroll_t4_filing_artifact import PayrollT4FilingArtifact
from app.models.payroll_t4_submission_attempt import PayrollT4SubmissionAttempt
from app.models.payroll_t4_submission_attempt_event import PayrollT4SubmissionAttemptEvent
from app.models.payroll_t4_submission_job import PayrollT4SubmissionJob
from app.models.payroll_run_audit_event import PayrollRunAuditEvent
from app.models.payroll_run import PayrollRun
from app.models.paystub import Paystub
from app.models.user_account import UserAccount
from app.services.account_security_service import create_user_account
from app.services.auth_service import create_access_token
from app.services.outbox_processor import process_outbox_batch
from app.services.payroll_t4_filing_artifact_service import get_payroll_t4_filing_artifact_row
from app.services.payroll_t4_xml_validation_service import (
    get_active_payroll_t4_xml_validator,
    validate_t4_xml_package,
)

client = TestClient(app)


def _save_company_profile(company_id: int, modules: list[str] | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(
            CompanyProfile(
                company_id=int(company_id),
                company_name=f"Company {company_id}",
                primary_trade="Foundations",
                country="CA",
                province_or_state="AB",
                cra_business_number="123456789",
                cra_payroll_program_account_number="RP0001",
                payroll_registration_country="CA",
                selected_tier="tier_3_full_system",
                enabled_modules=list(modules or ["payroll"]),
                onboarding_completed=True,
            )
        )
        db.commit()
    finally:
        db.close()


def _owner_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": f"owner-{company_id}", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    return {
        "Authorization": f"Bearer {resp.json()['access_token']}",
        "X-Company-Id": str(company_id),
    }


def _create_account(
    *,
    company_id: int,
    username: str,
    email: str,
    password: str,
    role: str,
    linked_employee_id: int | None = None,
) -> UserAccount:
    db = SessionLocal()
    try:
        return create_user_account(
            db=db,
            company_id=int(company_id),
            username=username,
            email=email,
            password=password,
            role=role,
            linked_employee_id=linked_employee_id,
        )
    finally:
        db.close()


def _login_headers(username: str, password: str, company_id: int) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}", "X-Company-Id": str(company_id)}


def _set_pin(headers: dict[str, str], pin: str) -> None:
    response = client.post("/employee-self-service/pin/set", headers=headers, json={"new_pin": pin})
    assert response.status_code == 200, response.text


def _seed_posted_run(
    *,
    company_id: int,
    payroll_run_id: str,
    pay_period_id: str,
    posted_at: datetime,
    employees: list[dict[str, object]],
) -> dict[str, int]:
    db = SessionLocal()
    try:
        pay_period = PayPeriod(
            pay_period_id=pay_period_id,
            company_id=int(company_id),
            start_date=date(posted_at.year, 1, 1),
            end_date=date(posted_at.year, 1, 14),
            status="POSTED",
        )
        payroll_run = PayrollRun(
            payroll_run_id=payroll_run_id,
            company_id=int(company_id),
            pay_period_id=pay_period_id,
            status="FINALIZED",
            posted_at=None,
        )
        db.add(pay_period)
        db.add(payroll_run)
        db.flush()

        employee_ids: dict[str, int] = {}
        for row in employees:
            existing_employee_id = row.get("employee_id")
            if existing_employee_id is None:
                employee = Employee(
                    company_id=int(company_id),
                    name=str(row["name"]),
                    legal_name=str(row["name"]),
                    hourly_rate_cents=3000,
                    employment_status="ACTIVE",
                    is_active=True,
                )
                db.add(employee)
                db.flush()
            else:
                employee = (
                    db.query(Employee)
                    .filter(Employee.company_id == int(company_id))
                    .filter(Employee.id == int(existing_employee_id))
                    .one()
                )

            employee_ids[str(row["name"])] = int(employee.id)
            paystub = Paystub(
                company_id=int(company_id),
                payroll_run_id=payroll_run_id,
                employee_id=int(employee.id),
                gross_pay_cents=int(row["gross_pay_cents"]),
                total_deductions_cents=0,
                net_pay_cents=int(row["gross_pay_cents"]),
            )
            db.add(paystub)
            db.flush()

            for deduction_type, amount_cents in dict(row.get("deductions", {})).items():
                db.add(
                    PayrollDeduction(
                        company_id=int(company_id),
                        payroll_run_id=payroll_run_id,
                        employee_id=int(employee.id),
                        paystub_id=str(paystub.paystub_id),
                        deduction_type=str(deduction_type),
                        amount_cents=int(amount_cents),
                        calculation_source="STATUTORY" if deduction_type in {"CPP", "EI", "TAX"} else "CONFIG",
                    )
                )
        payroll_run.status = "POSTED"
        payroll_run.posted_at = posted_at
        db.add(payroll_run)
        db.commit()
        return employee_ids
    finally:
        db.close()


def _prepare_ready_t4_submission_package(*, company_id: int, tax_year: int = 2026) -> dict[str, object]:
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id=f"pr-t4-submission-{company_id}-{tax_year}",
        pay_period_id=f"pp-t4-submission-{company_id}-{tax_year}",
        posted_at=datetime(tax_year, 6, 15, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Submission Worker",
                "gross_pay_cents": 83_000,
                "deductions": {"CPP": 4_980, "EI": 1_660, "TAX": 12_900},
            },
        ],
    )

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["Submission Worker"])
            .one()
        )
        employee.legal_name = "Submission Worker"
        employee.sin = "555444333"
        employee.address_line_1 = "500 Submission Way"
        employee.city = "Calgary"
        employee.province = "AB"
        employee.postal_code = "T2P4K8"
        employee.country = "CA"
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": tax_year})
    assert generated.status_code == 200, generated.text

    artifact = client.post(f"/payroll/t4s/filing-artifact?tax_year={tax_year}", headers=_owner_headers(company_id))
    assert artifact.status_code == 200, artifact.text

    xml_package = client.post(f"/payroll/t4s/xml-package?tax_year={tax_year}", headers=_owner_headers(company_id))
    assert xml_package.status_code == 200, xml_package.text
    return {"artifact": artifact.json(), "xml_package": xml_package.json()}


def test_generate_and_list_t4s_from_posted_payroll():
    company_id = 68101
    other_company_id = 68102
    _save_company_profile(company_id)
    _save_company_profile(other_company_id)

    own_employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-own-1",
        pay_period_id="pp-t4-own-1",
        posted_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        employees=[
            {
                "name": "T4 Worker A",
                "gross_pay_cents": 100_000,
                "deductions": {"CPP": 6_000, "EI": 2_000, "TAX": 18_000, "UNION_DUES": 1_000},
            },
            {
                "name": "T4 Worker B",
                "gross_pay_cents": 80_000,
                "deductions": {"CPP": 4_800, "EI": 1_600, "TAX": 12_000},
            },
        ],
    )
    _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-own-2",
        pay_period_id="pp-t4-own-2",
        posted_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        employees=[
            {
                "name": "T4 Worker A",
                "employee_id": own_employee_ids["T4 Worker A"],
                "gross_pay_cents": 20_000,
                "deductions": {"CPP": 1_200, "EI": 400, "TAX": 3_000},
            },
        ],
    )
    _seed_posted_run(
        company_id=other_company_id,
        payroll_run_id="pr-t4-other-1",
        pay_period_id="pp-t4-other-1",
        posted_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Foreign T4 Worker",
                "gross_pay_cents": 55_000,
                "deductions": {"CPP": 3_300, "EI": 1_100, "TAX": 9_000},
            },
        ],
    )

    generate = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generate.status_code == 200, generate.text
    assert generate.json() == {"tax_year": 2026, "generated": 2, "updated": 0, "source_payroll_runs": 2}

    other_generate = client.post(
        "/payroll/t4s/generate",
        headers=_owner_headers(other_company_id),
        json={"tax_year": 2026},
    )
    assert other_generate.status_code == 200, other_generate.text
    assert other_generate.json()["generated"] == 1

    slips = client.post("/payroll/t4s/slips/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert slips.status_code == 200, slips.text
    assert slips.json() == {"tax_year": 2026, "generated": 2, "regenerated": 0}

    other_slips = client.post(
        "/payroll/t4s/slips/generate",
        headers=_owner_headers(other_company_id),
        json={"tax_year": 2026},
    )
    assert other_slips.status_code == 200, other_slips.text
    assert other_slips.json()["generated"] == 1

    listed = client.get("/payroll/t4s?tax_year=2026", headers=_owner_headers(company_id))
    assert listed.status_code == 200, listed.text
    rows = listed.json()["rows"]
    assert len(rows) == 2
    assert {row["company_id"] for row in rows} == {company_id}
    assert all(row["status"] == "AVAILABLE" for row in rows)
    assert all(row["artifact_state"] == "AVAILABLE" for row in rows)
    assert all(row["artifact_available"] is True for row in rows)
    assert all(row["delivery_status"] == "PENDING_MANUAL" for row in rows)
    assert all(row["delivery_state"] == "PENDING_MANUAL" for row in rows)
    assert all(row["slip_url"] for row in rows)
    assert all(row["artifact_download_url"] == row["slip_url"] for row in rows)
    assert all(row["slip_file_name"].endswith(".pdf") for row in rows)
    assert all(row["slip_content_type"] == "application/pdf" for row in rows)
    assert all(row["slip_byte_size"] > 0 for row in rows)
    assert all(row["slip_available_at"] is not None for row in rows)
    assert all(row["delivered_at"] is None for row in rows)
    assert all(row["employee_download_count"] == 0 for row in rows)
    assert all(row["employee_has_downloaded"] is False for row in rows)
    assert all(row["employee_acknowledged_at"] is None for row in rows)
    assert all(row["employee_has_acknowledged"] is False for row in rows)
    assert all(row["record_id"] == row["t4_id"] for row in rows)
    assert all(row["employee_display_name"] == row["employee_name"] for row in rows)

    employee_a = next(row for row in rows if row["employee_id"] == own_employee_ids["T4 Worker A"])
    assert employee_a["employment_income_cents"] == 120_000
    assert employee_a["cpp_contributions_cents"] == 7_200
    assert employee_a["ei_premiums_cents"] == 2_400
    assert employee_a["income_tax_deducted_cents"] == 21_000
    assert employee_a["other_deductions_cents"] == 1_000

    filtered = client.get(
        f"/payroll/t4s?tax_year=2026&employee_id={own_employee_ids['T4 Worker B']}",
        headers=_owner_headers(company_id),
    )
    assert filtered.status_code == 200, filtered.text
    assert len(filtered.json()["rows"]) == 1
    assert filtered.json()["rows"][0]["employee_id"] == own_employee_ids["T4 Worker B"]

    download = client.get(employee_a["slip_url"], headers=_owner_headers(company_id))
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.headers["content-disposition"].endswith(f'"{employee_a["slip_file_name"]}"')
    assert download.content.startswith(b"%PDF-1.4")

    _create_account(
        company_id=company_id,
        username="t4-download-manager",
        email="t4-download-manager@example.com",
        password="T4DownloadManagerPass#1",
        role="MANAGER",
    )
    manager_headers = _login_headers("t4-download-manager", "T4DownloadManagerPass#1", company_id)
    denied_download = client.get(employee_a["slip_url"], headers=manager_headers)
    assert denied_download.status_code == 403
    assert denied_download.json()["detail"]["code"] == "permission_required"

    marked_delivered = client.post(f"/payroll/t4s/{employee_a['t4_id']}/mark_delivered", headers=_owner_headers(company_id))
    assert marked_delivered.status_code == 200, marked_delivered.text
    assert marked_delivered.json()["delivery_status"] == "DELIVERED_MANUAL"
    assert marked_delivered.json()["delivery_state"] == "DELIVERED_MANUAL"
    assert marked_delivered.json()["delivered_at"] is not None
    assert marked_delivered.json()["delivered_by_user_id"] == f"owner-{company_id}"

    marked_delivered_again = client.post(
        f"/payroll/t4s/{employee_a['t4_id']}/mark_delivered",
        headers=_owner_headers(company_id),
    )
    assert marked_delivered_again.status_code == 200, marked_delivered_again.text
    assert marked_delivered_again.json()["delivery_status"] == "DELIVERED_MANUAL"
    assert marked_delivered_again.json()["delivered_at"] == marked_delivered.json()["delivered_at"]
    assert marked_delivered_again.json()["delivered_by_user_id"] == marked_delivered.json()["delivered_by_user_id"]

    pending_only = client.get("/payroll/t4s?tax_year=2026&delivery_status=PENDING_MANUAL", headers=_owner_headers(company_id))
    assert pending_only.status_code == 200, pending_only.text
    assert len(pending_only.json()["rows"]) == 1
    assert pending_only.json()["rows"][0]["employee_id"] == own_employee_ids["T4 Worker B"]

    listed_after_download = client.get("/payroll/t4s?tax_year=2026", headers=_owner_headers(company_id))
    refreshed_employee_a = next(
        row for row in listed_after_download.json()["rows"] if row["employee_id"] == own_employee_ids["T4 Worker A"]
    )
    assert refreshed_employee_a["slip_download_count"] == 0
    assert refreshed_employee_a["slip_last_downloaded_at"] is None
    assert refreshed_employee_a["slip_last_downloaded_by_user_id"] is None
    assert refreshed_employee_a["employee_download_count"] == 0
    assert refreshed_employee_a["employee_has_downloaded"] is False
    assert refreshed_employee_a["employee_last_downloaded_at"] is None
    assert refreshed_employee_a["employee_acknowledged_at"] is None
    assert refreshed_employee_a["employee_has_acknowledged"] is False

    recorded_download = client.post(
        f"/payroll/t4s/{employee_a['t4_id']}/record-download",
        headers=_owner_headers(company_id),
    )
    assert recorded_download.status_code == 200, recorded_download.text
    assert recorded_download.json()["slip_download_count"] == 1
    assert recorded_download.json()["slip_last_downloaded_at"] is not None
    assert recorded_download.json()["slip_last_downloaded_by_user_id"] == f"owner-{company_id}"
    assert recorded_download.json()["employee_download_count"] == 0

    cross_company_download = client.get(employee_a["slip_url"], headers=_owner_headers(other_company_id))
    assert cross_company_download.status_code == 404

    cross_company_record_download = client.post(
        f"/payroll/t4s/{employee_a['t4_id']}/record-download",
        headers=_owner_headers(other_company_id),
    )
    assert cross_company_record_download.status_code == 404

    cross_company_mark_delivered = client.post(
        f"/payroll/t4s/{employee_a['t4_id']}/mark_delivered",
        headers=_owner_headers(other_company_id),
    )
    assert cross_company_mark_delivered.status_code == 404

    db = SessionLocal()
    try:
        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_marked_delivered_manual")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payload_json["t4_id"] == employee_a["t4_id"]
        assert audit_events[0].payload_json["delivery_status"] == "DELIVERED_MANUAL"
        assert audit_events[0].actor_user_id == f"owner-{company_id}"
    finally:
        db.close()


def test_payroll_t4s_empty_before_generation():
    company_id = 68103
    _save_company_profile(company_id)

    response = client.get("/payroll/t4s?tax_year=2026", headers=_owner_headers(company_id))

    assert response.status_code == 200, response.text
    assert response.json()["rows"] == []


def test_payroll_t4_output_generation_and_download_denies_unauthorized_and_stale_mfa():
    company_id = 68104
    _save_company_profile(company_id)
    _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-mfa-1",
        pay_period_id="pp-t4-mfa-1",
        posted_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
        employees=[
            {
                "name": "MFA T4 Worker",
                "gross_pay_cents": 72_000,
                "deductions": {"CPP": 4_320, "EI": 1_440, "TAX": 10_200},
            }
        ],
    )
    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    manager = _create_account(
        company_id=company_id,
        username="t4-manager",
        email="t4-manager@example.com",
        password="T4ManagerPass#1",
        role="MANAGER",
    )
    manager_headers = _login_headers("t4-manager", "T4ManagerPass#1", company_id)
    denied = client.post("/payroll/t4s/slips/generate", headers=manager_headers, json={"tax_year": 2026})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_required"

    accountant = _create_account(
        company_id=company_id,
        username="t4-accountant",
        email="t4-accountant@example.com",
        password="T4AccountantPass#1",
        role="ACCOUNTANT",
    )
    db = SessionLocal()
    try:
        db.query(UserAccount).filter(UserAccount.user_account_id == accountant.user_account_id).update({"mfa_enabled": True})
        db.commit()
    finally:
        db.close()

    fresh_token = create_access_token(
        user_id=accountant.user_account_id,
        company_id=company_id,
        mfa_authenticated=True,
        mfa_authenticated_at=datetime.now(timezone.utc).replace(microsecond=0),
    )
    fresh_headers = {"Authorization": f"Bearer {fresh_token}", "X-Company-Id": str(company_id)}
    fresh_allowed = client.post("/payroll/t4s/slips/generate", headers=fresh_headers, json={"tax_year": 2026})
    assert fresh_allowed.status_code == 200, fresh_allowed.text

    listed = client.get("/payroll/t4s?tax_year=2026", headers=_owner_headers(company_id))
    assert listed.status_code == 200, listed.text
    t4_id = listed.json()["rows"][0]["t4_id"]

    fresh_delivery = client.post(f"/payroll/t4s/{t4_id}/mark_delivered", headers=fresh_headers)
    assert fresh_delivery.status_code == 200, fresh_delivery.text
    assert fresh_delivery.json()["delivery_status"] == "DELIVERED_MANUAL"

    stale_token = create_access_token(
        user_id=accountant.user_account_id,
        company_id=company_id,
        mfa_authenticated=True,
        mfa_authenticated_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    stale_headers = {"Authorization": f"Bearer {stale_token}", "X-Company-Id": str(company_id)}
    denied_mfa = client.post("/payroll/t4s/slips/generate", headers=stale_headers, json={"tax_year": 2026})
    assert denied_mfa.status_code == 403
    assert denied_mfa.json()["detail"]["code"] == "fresh_mfa_required"

    denied_delivery_mfa = client.post(f"/payroll/t4s/{t4_id}/mark_delivered", headers=stale_headers)
    assert denied_delivery_mfa.status_code == 403
    assert denied_delivery_mfa.json()["detail"]["code"] == "fresh_mfa_required"


def test_payroll_admin_cannot_mark_unavailable_t4_as_delivered():
    company_id = 681041
    _save_company_profile(company_id)
    _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-unavailable-1",
        pay_period_id="pp-t4-unavailable-1",
        posted_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Unavailable T4 Worker",
                "gross_pay_cents": 72_000,
                "deductions": {"CPP": 4_320, "EI": 1_440, "TAX": 11_000},
            },
        ],
    )

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    listed = client.get("/payroll/t4s?tax_year=2026", headers=_owner_headers(company_id))
    assert listed.status_code == 200, listed.text
    t4_id = listed.json()["rows"][0]["t4_id"]
    assert listed.json()["rows"][0]["artifact_state"] == "NOT_GENERATED"

    response = client.post(f"/payroll/t4s/{t4_id}/mark_delivered", headers=_owner_headers(company_id))
    assert response.status_code == 409
    assert response.json()["detail"] == "T4 slip is not available"


def test_payroll_t4_export_preparation_reports_real_readiness_and_blockers():
    company_id = 681045
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-export-1",
        pay_period_id="pp-t4-export-1",
        posted_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Export Ready Worker",
                "gross_pay_cents": 88_000,
                "deductions": {"CPP": 5_280, "EI": 1_760, "TAX": 13_500},
            },
            {
                "name": "Export Blocked Worker",
                "gross_pay_cents": 63_000,
                "deductions": {"CPP": 3_780, "EI": 1_260, "TAX": 9_400},
            },
        ],
    )

    db = SessionLocal()
    try:
        ready_employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["Export Ready Worker"])
            .one()
        )
        ready_employee.legal_name = "Export Ready Worker"
        ready_employee.sin = "123456789"
        ready_employee.address_line_1 = "123 Main St"
        ready_employee.city = "Calgary"
        ready_employee.province = "AB"
        ready_employee.postal_code = "T2P1J9"
        ready_employee.country = "CA"

        blocked_employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["Export Blocked Worker"])
            .one()
        )
        blocked_employee.legal_name = "Export Blocked Worker"
        blocked_employee.sin = None
        blocked_employee.address_line_1 = None
        blocked_employee.city = None
        blocked_employee.province = None
        blocked_employee.postal_code = None
        blocked_employee.country = None
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    export = client.get("/payroll/t4s/export-preparation?tax_year=2026", headers=_owner_headers(company_id))
    assert export.status_code == 200, export.text
    body = export.json()

    assert body["tax_authority"] == "CRA"
    assert body["tax_year"] == 2026
    assert body["export_status"] == "EXPORT_PREPARATION_BLOCKED"
    assert body["export_ready"] is False
    assert body["summary"]["t4_record_count"] == 2
    assert body["summary"]["ready_record_count"] == 1
    assert body["summary"]["artifact_available_count"] == 0
    assert body["company"]["company_id"] == company_id
    assert any(issue["code"] == "employee_sin_missing" for issue in body["blocking_issues"])
    assert any(issue["code"] == "employee_address_missing" for issue in body["blocking_issues"])

    ready_row = next(row for row in body["rows"] if row["employee_id"] == employee_ids["Export Ready Worker"])
    blocked_row = next(row for row in body["rows"] if row["employee_id"] == employee_ids["Export Blocked Worker"])
    assert ready_row["ready_for_export"] is True
    assert ready_row["artifact_state"] == "NOT_GENERATED"
    assert blocked_row["ready_for_export"] is False
    assert "employee_sin_missing" in blocked_row["blocking_issue_codes"]
    assert "employee_address_missing" in blocked_row["blocking_issue_codes"]

    db = SessionLocal()
    try:
        assert (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_export_prepared")
            .count()
        ) == 0
    finally:
        db.close()

    prepared = client.post("/payroll/t4s/export-preparation?tax_year=2026", headers=_owner_headers(company_id))
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["export_status"] == body["export_status"]
    assert prepared.json()["summary"] == body["summary"]
    assert prepared.json()["blocking_issues"] == body["blocking_issues"]

    db = SessionLocal()
    try:
        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_export_prepared")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payroll_run_id is None
        assert audit_events[0].actor_user_id == f"owner-{company_id}"
        assert audit_events[0].payload_json["tax_year"] == 2026
        assert audit_events[0].payload_json["export_status"] == "EXPORT_PREPARATION_BLOCKED"
        assert "employee_sin_missing" in audit_events[0].payload_json["blocking_issue_codes"]
    finally:
        db.close()


def test_payroll_t4_filing_artifact_blocks_when_company_cra_identifiers_are_missing():
    company_id = 68108
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-filing-blocked-1",
        pay_period_id="pp-t4-filing-blocked-1",
        posted_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Filing Blocked Worker",
                "gross_pay_cents": 75_000,
                "deductions": {"CPP": 4_500, "EI": 1_500, "TAX": 12_000},
            },
        ],
    )

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["Filing Blocked Worker"])
            .one()
        )
        employee.legal_name = "Filing Blocked Worker"
        employee.sin = "321654987"
        employee.address_line_1 = "700 Centre St"
        employee.city = "Calgary"
        employee.province = "AB"
        employee.postal_code = "T2G5P6"
        employee.country = "CA"

        profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).one()
        profile.cra_business_number = None
        profile.cra_payroll_program_account_number = None
        profile.payroll_registration_country = None
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    filing = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert filing.status_code == 200, filing.text
    body = filing.json()

    assert body["filing_status"] == "FILING_ARTIFACT_BLOCKED"
    assert body["export_ready"] is False
    assert body["filing_ready"] is False
    assert any(issue["code"] == "cra_business_number_missing" for issue in body["blocking_issues"])
    assert any(issue["code"] == "cra_payroll_program_account_number_missing" for issue in body["blocking_issues"])
    assert any(issue["code"] == "payroll_registration_country_missing" for issue in body["blocking_issues"])
    assert body["prepared_payload"]["filing_status"] == "FILING_ARTIFACT_BLOCKED"
    assert body["filing_package"]["schema_id"] == "frontier_payroll_cra_t4_filing_package"
    assert body["filing_package"]["schema_version"] == "1.0"
    assert body["filing_package"]["package_kind"] == "CRA_T4_FILING_PACKAGE_PREPARATION"
    assert body["filing_package"]["filing_status"] == "FILING_ARTIFACT_BLOCKED"
    assert body["filing_artifact"]["file_name"] == "t4-filing-package-2026.json"


def test_payroll_t4_xml_package_can_be_generated_from_canonical_filing_artifact():
    company_id = 681081
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-xml-1",
        pay_period_id="pp-t4-xml-1",
        posted_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        employees=[
            {
                "name": "XML Worker",
                "gross_pay_cents": 77_000,
                "deductions": {"CPP": 4_620, "EI": 1_540, "TAX": 11_700},
            },
        ],
    )

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["XML Worker"])
            .one()
        )
        employee.legal_name = "XML Worker"
        employee.sin = "123456789"
        employee.address_line_1 = "100 XML Ave"
        employee.city = "Calgary"
        employee.province = "AB"
        employee.postal_code = "T2P1X1"
        employee.country = "CA"
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    artifact = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert artifact.status_code == 200, artifact.text

    xml_package = client.post("/payroll/t4s/xml-package?tax_year=2026", headers=_owner_headers(company_id))
    assert xml_package.status_code == 200, xml_package.text
    body = xml_package.json()

    assert body["tax_year"] == 2026
    assert body["filing_status"] == "FILING_ARTIFACT_READY"
    assert body["source_filing_artifact"]["file_name"] == "t4-filing-package-2026.json"
    assert body["xml_package"]["schema_id"] == "frontier_payroll_cra_t4_xml_package"
    assert body["xml_package"]["schema_version"] == "1.0"
    assert body["xml_package"]["package_kind"] == "CRA_T4_XML_SCHEMA_ALIGNED_PACKAGE"
    assert body["xml_package"]["source_schema_id"] == "frontier_payroll_cra_t4_filing_package"
    assert body["xml_package"]["source_schema_version"] == "1.0"
    assert body["xml_package"]["file_name"] == "t4-filing-package-2026.xml"
    assert body["xml_package"]["content_type"] == "application/xml"
    assert body["xml_package"]["byte_size"] > 0
    assert body["xml_package"]["sha256"]
    assert body["xml_package"]["generated_by_user_id"] == f"owner-{company_id}"
    assert body["validation"]["validator_id"] == "frontier_internal_payroll_t4_xml_validator"
    assert body["validation"]["validator_version"] == "1.0"
    assert body["validation"]["validation_mode"] == "INTERNAL_ONLY"
    assert body["validation"]["status"] == "VALID"
    assert body["validation"]["xml_package_sha256"] == body["xml_package"]["sha256"]
    assert body["validation"]["validated_by_user_id"] == f"owner-{company_id}"
    assert body["validation"]["result"]["target_schema_id"] == "frontier_payroll_cra_t4_xml_package"
    assert body["validation"]["result"]["issue_count"] == 0
    assert body["validation"]["result"]["issues"] == []
    assert body["xml"].startswith('<?xml version="1.0" encoding="UTF-8"?>\n<PayrollT4XmlPackage ')
    assert "<CompanyName>Company 681081</CompanyName>" in body["xml"]
    assert "<LegalName>XML Worker</LegalName>" in body["xml"]
    assert "<Sin>123456789</Sin>" in body["xml"]

    db = SessionLocal()
    try:
        artifact_row = (
            db.query(PayrollT4FilingArtifact)
            .filter(PayrollT4FilingArtifact.company_id == company_id)
            .filter(PayrollT4FilingArtifact.tax_year == 2026)
            .one()
        )
        assert artifact_row.xml_package_schema_id == "frontier_payroll_cra_t4_xml_package"
        assert artifact_row.xml_package_schema_version == "1.0"
        assert artifact_row.xml_package_file_name == "t4-filing-package-2026.xml"
        assert artifact_row.xml_package_content_type == "application/xml"
        assert artifact_row.xml_package_byte_size == body["xml_package"]["byte_size"]
        assert artifact_row.xml_package_sha256 == body["xml_package"]["sha256"]
        assert artifact_row.xml_generated_by_user_id == f"owner-{company_id}"
        assert artifact_row.xml_validation_validator_id == "frontier_internal_payroll_t4_xml_validator"
        assert artifact_row.xml_validation_validator_version == "1.0"
        assert artifact_row.xml_validation_mode == "INTERNAL_ONLY"
        assert artifact_row.xml_validation_status == "VALID"
        assert artifact_row.xml_validation_xml_sha256 == body["xml_package"]["sha256"]
        assert artifact_row.xml_validated_by_user_id == f"owner-{company_id}"
        assert artifact_row.xml_package_blob.decode("utf-8") == body["xml"]

        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_xml_validation_passed")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payload_json["tax_year"] == 2026
        assert audit_events[0].payload_json["status"] == "VALID"
        assert audit_events[0].payload_json["xml_package_sha256"] == body["xml_package"]["sha256"]
    finally:
        db.close()


def test_payroll_t4_xml_package_missing_required_inputs_fail_clearly():
    company_id = 681082
    _save_company_profile(company_id)
    _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-xml-blocked-1",
        pay_period_id="pp-t4-xml-blocked-1",
        posted_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        employees=[
            {
                "name": "XML Blocked Worker",
                "gross_pay_cents": 55_000,
                "deductions": {"CPP": 3_300, "EI": 1_100, "TAX": 8_400},
            },
        ],
    )

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    xml_package = client.post("/payroll/t4s/xml-package?tax_year=2026", headers=_owner_headers(company_id))
    assert xml_package.status_code == 409, xml_package.text
    detail = xml_package.json()["detail"]

    assert detail["code"] == "xml_package_validation_failed"
    assert any(error["path"] == "t4_rows[0].employee_sin" for error in detail["validation_errors"])
    assert any(
        error["path"] == "t4_rows[0].employee_address.address_line_1" for error in detail["validation_errors"]
    )
    assert any(error["error_code"] == error["code"] for error in detail["validation_errors"])
    assert any(error["error_message"] == error["message"] for error in detail["validation_errors"])
    assert any(error["validation_section"] == "T4_ROWS" for error in detail["validation_errors"])
    assert all("validation_line_reference" in error for error in detail["validation_errors"])


def test_payroll_t4_xml_package_get_is_read_only_and_requires_prepared_xml():
    company_id = 6810821
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-xml-readonly-1",
        pay_period_id="pp-t4-xml-readonly-1",
        posted_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
        employees=[
            {
                "name": "XML Read Only Worker",
                "gross_pay_cents": 61_000,
                "deductions": {"CPP": 3_660, "EI": 1_220, "TAX": 9_800},
            },
        ],
    )

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["XML Read Only Worker"])
            .one()
        )
        employee.legal_name = "XML Read Only Worker"
        employee.sin = "111222333"
        employee.address_line_1 = "200 Readonly Rd"
        employee.city = "Calgary"
        employee.province = "AB"
        employee.postal_code = "T2P2B2"
        employee.country = "CA"
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    artifact = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert artifact.status_code == 200, artifact.text

    before_generation = client.get("/payroll/t4s/xml-package?tax_year=2026", headers=_owner_headers(company_id))
    assert before_generation.status_code == 404
    assert before_generation.json()["detail"] == "Payroll T4 XML package not found"

    db = SessionLocal()
    try:
        assert (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_xml_package_generated")
            .count()
        ) == 0
    finally:
        db.close()

    prepared = client.post("/payroll/t4s/xml-package?tax_year=2026", headers=_owner_headers(company_id))
    assert prepared.status_code == 200, prepared.text

    fetched = client.get("/payroll/t4s/xml-package?tax_year=2026", headers=_owner_headers(company_id))
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == prepared.json()

    db = SessionLocal()
    try:
        assert (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_xml_package_generated")
            .count()
        ) == 1
        assert (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_xml_package_regenerated")
            .count()
        ) == 0
    finally:
        db.close()


def test_payroll_t4_xml_validation_storage_persists_structured_failure_detail():
    company_id = 681083
    _prepare_ready_t4_submission_package(company_id=company_id)

    db = SessionLocal()
    try:
        artifact_row = get_payroll_t4_filing_artifact_row(db=db, company_id=company_id, tax_year=2026)
        assert artifact_row is not None

        artifact_row.xml_package_blob = b"<PayrollT4XmlPackage>\n  <EmployerRegistration>"
        artifact_row.xml_package_sha256 = "invalid-xml-package-sha"
        artifact_row.xml_validation_status = None
        artifact_row.xml_validation_result_json = None
        artifact_row.xml_validation_xml_sha256 = None
        artifact_row.xml_validated_at = None
        artifact_row.xml_validated_by_user_id = None

        result = validate_t4_xml_package(
            db=db,
            artifact_row=artifact_row,
            company_id=company_id,
            tax_year=2026,
            actor_user_id=f"owner-{company_id}",
        )
        db.commit()

        assert result["status"] == "INVALID"
        assert result["result"]["issue_count"] >= 1
        first_issue = result["result"]["issues"][0]
        assert first_issue["code"] == "xml_not_well_formed"
        assert first_issue["error_code"] == "xml_not_well_formed"
        assert "not well formed" in first_issue["error_message"]
        assert first_issue["validation_section"] == "XML_DOCUMENT"
        assert first_issue["validation_line_reference"] is not None

        db.refresh(artifact_row)
        stored_issue = artifact_row.xml_validation_result_json["issues"][0]
        assert stored_issue["error_code"] == "xml_not_well_formed"
        assert stored_issue["error_message"] == first_issue["error_message"]
        assert stored_issue["validation_section"] == "XML_DOCUMENT"
        assert stored_issue["validation_line_reference"] == first_issue["validation_line_reference"]
    finally:
        db.close()


def test_payroll_t4_filing_artifact_returns_correct_summary_totals_and_requested_tax_year_rows():
    company_id = 68109
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-filing-ready-1",
        pay_period_id="pp-t4-filing-ready-1",
        posted_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Filing Worker A",
                "gross_pay_cents": 100_000,
                "deductions": {"CPP": 6_000, "EI": 2_000, "TAX": 18_000, "UNION_DUES": 1_000},
            },
            {
                "name": "Filing Worker B",
                "gross_pay_cents": 60_000,
                "deductions": {"CPP": 3_600, "EI": 1_200, "TAX": 9_000},
            },
        ],
    )
    _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-filing-ready-2",
        pay_period_id="pp-t4-filing-ready-2",
        posted_at=datetime(2025, 12, 20, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Prior Year Worker",
                "gross_pay_cents": 50_000,
                "deductions": {"CPP": 3_000, "EI": 1_000, "TAX": 7_000},
            },
        ],
    )

    db = SessionLocal()
    try:
        for employee_name, employee_id in employee_ids.items():
            employee = (
                db.query(Employee)
                .filter(Employee.company_id == company_id)
                .filter(Employee.id == employee_id)
                .one()
            )
            employee.legal_name = employee_name
            employee.sin = "123123123" if employee_name.endswith("A") else "456456456"
            employee.address_line_1 = "100 Payroll Ave"
            employee.city = "Calgary"
            employee.province = "AB"
            employee.postal_code = "T2P1A1"
            employee.country = "CA"
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    slips = client.post("/payroll/t4s/slips/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert slips.status_code == 200, slips.text

    listed = client.get("/payroll/t4s?tax_year=2026", headers=_owner_headers(company_id))
    assert listed.status_code == 200, listed.text
    first_row = listed.json()["rows"][0]
    marked_delivered = client.post(f"/payroll/t4s/{first_row['t4_id']}/mark_delivered", headers=_owner_headers(company_id))
    assert marked_delivered.status_code == 200, marked_delivered.text
    downloaded = client.get(first_row["slip_url"], headers=_owner_headers(company_id))
    assert downloaded.status_code == 200, downloaded.text

    db = SessionLocal()
    try:
        refreshed = db.query(Employee).filter(Employee.company_id == company_id).filter(Employee.id == employee_ids["Filing Worker A"]).one()
        refreshed.legal_name = "Filing Worker A"
        db.commit()
    finally:
        db.close()

    filing = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert filing.status_code == 200, filing.text
    body = filing.json()

    assert body["filing_status"] == "FILING_ARTIFACT_READY"
    assert body["export_ready"] is True
    assert body["filing_ready"] is True
    assert body["filing_package"]["schema_id"] == "frontier_payroll_cra_t4_filing_package"
    assert body["filing_package"]["schema_version"] == "1.0"
    assert body["filing_package"]["package_kind"] == "CRA_T4_FILING_PACKAGE_PREPARATION"
    assert body["summary"] == {
        "t4_record_count": 2,
        "employment_income_cents": 160_000,
        "cpp_contributions_cents": 9_600,
        "ei_premiums_cents": 3_200,
        "income_tax_deducted_cents": 27_000,
        "other_deductions_cents": 1_000,
        "delivered_count": 1,
        "employee_downloaded_count": 0,
        "employee_acknowledged_count": 0,
    }
    assert len(body["rows"]) == 2
    assert {row["employee_display_name"] for row in body["rows"]} == {"Filing Worker A", "Filing Worker B"}
    assert all(row["tax_year"] == 2026 for row in body["rows"])
    assert all(row["ready_for_filing"] is True for row in body["rows"])
    assert body["prepared_payload"]["employer_summary"]["other_deductions_cents"] == 1_000
    assert body["filing_package"]["employer_summary"]["other_deductions_cents"] == 1_000
    assert [row["employee_display_name"] for row in body["filing_package"]["t4_rows"]] == [
        "Filing Worker A",
        "Filing Worker B",
    ]

    db = SessionLocal()
    try:
        artifact_row = (
            db.query(PayrollT4FilingArtifact)
            .filter(PayrollT4FilingArtifact.company_id == company_id)
            .filter(PayrollT4FilingArtifact.tax_year == 2026)
            .one()
        )
        assert artifact_row.filing_status == "FILING_ARTIFACT_READY"
        assert artifact_row.artifact_file_name == "t4-filing-package-2026.json"
        assert artifact_row.artifact_content_type == "application/json"
        assert artifact_row.artifact_byte_size > 0
        assert artifact_row.prepared_payload_json["employer_summary"]["t4_record_count"] == 2
        assert artifact_row.prepared_payload_json["schema_id"] == "frontier_payroll_cra_t4_filing_package"
    finally:
        db.close()


def test_payroll_t4_filing_artifact_writes_audit_event():
    company_id = 68110
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-filing-audit-1",
        pay_period_id="pp-t4-filing-audit-1",
        posted_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Filing Audit Worker",
                "gross_pay_cents": 82_000,
                "deductions": {"CPP": 4_920, "EI": 1_640, "TAX": 12_500},
            },
        ],
    )

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["Filing Audit Worker"])
            .one()
        )
        employee.legal_name = "Filing Audit Worker"
        employee.sin = "741852963"
        employee.address_line_1 = "10 Audit Way"
        employee.city = "Calgary"
        employee.province = "AB"
        employee.postal_code = "T2P3A3"
        employee.country = "CA"
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    filing = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert filing.status_code == 200, filing.text

    db = SessionLocal()
    try:
        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_filing_artifact_prepared")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].actor_user_id == f"owner-{company_id}"
        assert audit_events[0].payload_json["tax_year"] == 2026
        assert audit_events[0].payload_json["filing_status"] == "FILING_ARTIFACT_READY"
        assert audit_events[0].payload_json["artifact_file_name"] == "t4-filing-package-2026.json"
        assert audit_events[0].payload_json["package_schema_id"] == "frontier_payroll_cra_t4_filing_package"
        assert audit_events[0].payload_json["package_schema_version"] == "1.0"
    finally:
        db.close()


def test_payroll_t4_xml_package_writes_generation_and_regeneration_audit_events():
    company_id = 681101
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-xml-audit-1",
        pay_period_id="pp-t4-xml-audit-1",
        posted_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        employees=[
            {
                "name": "XML Audit Worker",
                "gross_pay_cents": 82_000,
                "deductions": {"CPP": 4_920, "EI": 1_640, "TAX": 12_500},
            },
        ],
    )

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["XML Audit Worker"])
            .one()
        )
        employee.legal_name = "XML Audit Worker"
        employee.sin = "741852963"
        employee.address_line_1 = "10 Audit Way"
        employee.city = "Calgary"
        employee.province = "AB"
        employee.postal_code = "T2P3A3"
        employee.country = "CA"
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    first = client.post("/payroll/t4s/xml-package?tax_year=2026", headers=_owner_headers(company_id))
    assert first.status_code == 200, first.text

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["XML Audit Worker"])
            .one()
        )
        employee.legal_name = "XML Audit Worker Updated"
        db.commit()
    finally:
        db.close()

    second = client.post("/payroll/t4s/xml-package?tax_year=2026", headers=_owner_headers(company_id))
    assert second.status_code == 200, second.text
    assert first.json()["xml_package"]["sha256"] != second.json()["xml_package"]["sha256"]

    db = SessionLocal()
    try:
        generated_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_xml_package_generated")
            .all()
        )
        regenerated_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_xml_package_regenerated")
            .all()
        )
        validation_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_xml_validation_passed")
            .order_by(PayrollRunAuditEvent.id.asc())
            .all()
        )
        artifact_row = (
            db.query(PayrollT4FilingArtifact)
            .filter(PayrollT4FilingArtifact.company_id == company_id)
            .filter(PayrollT4FilingArtifact.tax_year == 2026)
            .one()
        )
        assert len(generated_events) == 1
        assert len(regenerated_events) == 1
        assert len(validation_events) == 2
        assert generated_events[0].payload_json["tax_year"] == 2026
        assert generated_events[0].payload_json["schema_id"] == "frontier_payroll_cra_t4_xml_package"
        assert generated_events[0].payload_json["schema_version"] == "1.0"
        assert generated_events[0].payload_json["actor_user_id"] == f"owner-{company_id}"
        assert generated_events[0].payload_json["xml_hash"] == first.json()["xml_package"]["sha256"]
        assert regenerated_events[0].payload_json["xml_hash"] == second.json()["xml_package"]["sha256"]
        assert validation_events[0].payload_json["xml_package_sha256"] == first.json()["xml_package"]["sha256"]
        assert validation_events[1].payload_json["xml_package_sha256"] == second.json()["xml_package"]["sha256"]
        assert artifact_row.xml_validation_status == "VALID"
        assert artifact_row.xml_validation_xml_sha256 == second.json()["xml_package"]["sha256"]
    finally:
        db.close()


def test_payroll_admin_can_create_and_list_t4_submission_jobs_from_existing_package():
    company_id = 681111
    prepared = _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    body = created.json()

    assert body["company_id"] == company_id
    assert body["tax_year"] == 2026
    assert body["status"] == "PREPARED"
    assert body["workflow_mode"] == "MANUAL_ONLY"
    assert body["workflow_stage"] == "PREPARED"
    assert body["next_expected_action"] == "QUEUE_OR_RECORD_MANUAL_TRANSMISSION"
    assert body["allowed_actions"] == ["QUEUE", "RECORD_MANUAL_TRANSMISSION", "RECORD_MANUAL_FAILURE"]
    assert body["blocked_actions"] == {
        "RETRY": "Submission job can only be retried from FAILED_MANUAL or RESPONSE_REJECTED_MANUAL status",
        "RECORD_MANUAL_RESPONSE": "CRA response can only be recorded after transmission is recorded"
    }
    assert body["terminal_outcome"] == "IN_PROGRESS"
    assert body["terminal_outcome_detail"] is None
    assert body["final_outcome"] is None
    assert body["final_outcome_detail"] is None
    assert body["can_queue"] is True
    assert body["can_retry"] is False
    assert body["can_record_manual_transmission"] is True
    assert body["can_record_manual_response"] is False
    assert body["can_record_manual_failure"] is True
    assert body["transmission_reference"] is None
    assert body["artifact_sha256"] == prepared["artifact"]["filing_artifact"]["sha256"]
    assert body["xml_package_sha256"] == prepared["xml_package"]["xml_package"]["sha256"]
    assert body["validation_validator_id"] == "frontier_internal_payroll_t4_xml_validator"
    assert body["validation_validator_version"] == "1.0"
    assert body["validation_mode"] == "INTERNAL_ONLY"
    assert body["validation_status"] == "VALID"
    assert body["validated_at"] == prepared["xml_package"]["validation"]["validated_at"]
    assert body["validated_by_user_id"] == f"owner-{company_id}"

    created_again = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created_again.status_code == 200, created_again.text
    assert created_again.json()["id"] == body["id"]
    assert created_again.json()["created_at"] == body["created_at"]

    listed = client.get("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert listed.status_code == 200, listed.text
    assert listed.json()["summary"] == {
        "total": 1,
        "in_progress": 1,
        "accepted": 0,
        "rejected": 0,
        "failed_manual": 0,
        "actionable": 1,
        "queued_manual_pending_transmission": 0,
        "transmitted_manual_pending_response": 0,
        "terminal": 0,
    }
    assert listed.json()["rows"] == [created_again.json()]

    detail = client.get(f"/payroll/t4s/submission-jobs/{body['id']}", headers=_owner_headers(company_id))
    assert detail.status_code == 200, detail.text
    assert detail.json() == body

    db = SessionLocal()
    try:
        rows = db.query(PayrollT4SubmissionJob).filter(PayrollT4SubmissionJob.company_id == company_id).all()
        assert len(rows) == 1
        assert rows[0].xml_package_sha256 == prepared["xml_package"]["xml_package"]["sha256"]

        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_created")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payload_json["submission_job_id"] == body["id"]
        assert audit_events[0].payload_json["filing_artifact_id"] == body["filing_artifact_id"]
        assert audit_events[0].payload_json["tax_year"] == 2026
        assert audit_events[0].payload_json["actor_user_id"] == f"owner-{company_id}"
        assert audit_events[0].payload_json["status"] == "PREPARED"
        assert audit_events[0].payload_json["artifact_sha256"] == body["artifact_sha256"]
        assert audit_events[0].payload_json["xml_hash"] == body["xml_package_sha256"]
        assert audit_events[0].payload_json["xml_package_sha256"] == body["xml_package_sha256"]
        assert audit_events[0].payload_json["validation_validator_id"] == "frontier_internal_payroll_t4_xml_validator"
        assert audit_events[0].payload_json["validation_validator_version"] == body["validation_validator_version"]
        assert audit_events[0].payload_json["validation_mode"] == body["validation_mode"]
        assert audit_events[0].payload_json["validation_status"] == "VALID"
        assert audit_events[0].payload_json["validated_at"] == body["validated_at"]
        assert audit_events[0].payload_json["validated_by_user_id"] == body["validated_by_user_id"]
    finally:
        db.close()


def test_t4_submission_job_creation_fails_when_filing_artifact_is_missing():
    company_id = 681112
    _save_company_profile(company_id)

    response = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert response.status_code == 409
    assert response.json()["detail"] == "Payroll T4 filing artifact not found for tax year 2026"


def test_t4_submission_job_creation_fails_when_xml_package_is_missing():
    company_id = 681113
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-submission-missing-xml-1",
        pay_period_id="pp-t4-submission-missing-xml-1",
        posted_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Missing XML Worker",
                "gross_pay_cents": 78_000,
                "deductions": {"CPP": 4_680, "EI": 1_560, "TAX": 11_800},
            },
        ],
    )

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["Missing XML Worker"])
            .one()
        )
        employee.legal_name = "Missing XML Worker"
        employee.sin = "222333444"
        employee.address_line_1 = "10 XML Missing St"
        employee.city = "Calgary"
        employee.province = "AB"
        employee.postal_code = "T2P8K1"
        employee.country = "CA"
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    artifact = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert artifact.status_code == 200, artifact.text

    response = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert response.status_code == 409
    assert response.json()["detail"] == "Payroll T4 XML package not found for tax year 2026"


def test_t4_submission_job_creation_fails_when_xml_validation_is_missing():
    company_id = 681117
    _prepare_ready_t4_submission_package(company_id=company_id)

    db = SessionLocal()
    try:
        artifact_row = (
            db.query(PayrollT4FilingArtifact)
            .filter(PayrollT4FilingArtifact.company_id == company_id)
            .filter(PayrollT4FilingArtifact.tax_year == 2026)
            .one()
        )
        artifact_row.xml_validation_validator_id = None
        artifact_row.xml_validation_validator_version = None
        artifact_row.xml_validation_mode = None
        artifact_row.xml_validation_status = None
        artifact_row.xml_validation_result_json = None
        artifact_row.xml_validation_xml_sha256 = None
        artifact_row.xml_validated_at = None
        artifact_row.xml_validated_by_user_id = None
        db.commit()
    finally:
        db.close()

    response = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert response.status_code == 409
    assert response.json()["detail"] == "Payroll T4 XML validation result not found for tax year 2026"


def test_t4_submission_job_creation_fails_when_xml_validation_version_is_no_longer_supported():
    company_id = 681121
    _prepare_ready_t4_submission_package(company_id=company_id)

    active_validator = get_active_payroll_t4_xml_validator()

    db = SessionLocal()
    try:
        artifact_row = (
            db.query(PayrollT4FilingArtifact)
            .filter(PayrollT4FilingArtifact.company_id == company_id)
            .filter(PayrollT4FilingArtifact.tax_year == 2026)
            .one()
        )
        artifact_row.xml_validation_validator_id = active_validator.validator_id
        artifact_row.xml_validation_validator_version = "0.9"
        db.commit()
    finally:
        db.close()

    response = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert response.status_code == 409
    assert response.json()["detail"] == "Payroll T4 XML validation version is stale for tax year 2026"


def test_t4_filing_artifact_regeneration_invalidates_stale_xml_validation():
    company_id = 681118
    _prepare_ready_t4_submission_package(company_id=company_id)

    db = SessionLocal()
    try:
        profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).one()
        profile.company_name = "Updated Company Name"
        db.commit()
    finally:
        db.close()

    artifact = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert artifact.status_code == 200, artifact.text

    db = SessionLocal()
    try:
        artifact_row = (
            db.query(PayrollT4FilingArtifact)
            .filter(PayrollT4FilingArtifact.company_id == company_id)
            .filter(PayrollT4FilingArtifact.tax_year == 2026)
            .one()
        )
        assert artifact_row.xml_package_sha256 is not None
        assert artifact_row.xml_validation_status is None
        assert artifact_row.xml_validation_result_json is None
        assert artifact_row.xml_validation_xml_sha256 is None
    finally:
        db.close()


def test_t4_submission_jobs_are_company_scoped():
    company_id = 681114
    other_company_id = 681115
    _prepare_ready_t4_submission_package(company_id=company_id)
    _prepare_ready_t4_submission_package(company_id=other_company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    own_list = client.get("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert own_list.status_code == 200, own_list.text
    assert own_list.json()["summary"]["total"] == 1
    assert len(own_list.json()["rows"]) == 1
    assert own_list.json()["rows"][0]["company_id"] == company_id
    assert own_list.json()["rows"][0]["validation_status"] == "VALID"

    other_list = client.get("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(other_company_id))
    assert other_list.status_code == 200, other_list.text
    assert other_list.json()["summary"] == {
        "total": 0,
        "in_progress": 0,
        "accepted": 0,
        "rejected": 0,
        "failed_manual": 0,
        "actionable": 0,
        "queued_manual_pending_transmission": 0,
        "transmitted_manual_pending_response": 0,
        "terminal": 0,
    }
    assert other_list.json()["rows"] == []

    cross_company_detail = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}",
        headers=_owner_headers(other_company_id),
    )
    assert cross_company_detail.status_code == 404


def test_t4_submission_job_list_reflects_monitoring_summary_counts():
    company_id = 681132
    _prepare_ready_t4_submission_package(company_id=company_id)
    prepared_response = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert prepared_response.status_code == 200, prepared_response.text
    prepared = prepared_response.json()

    created_at = datetime.fromisoformat(prepared["created_at"].replace("Z", "+00:00"))
    validated_at = datetime.fromisoformat(prepared["validated_at"].replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        db.add_all(
            [
                PayrollT4SubmissionJob(
                    company_id=company_id,
                    tax_year=2026,
                    filing_artifact_id=prepared["filing_artifact_id"],
                    status="PREPARED",
                    created_at=created_at + timedelta(minutes=1),
                    created_by_user_id=prepared["created_by_user_id"],
                    queued_at=created_at + timedelta(minutes=2),
                    filing_artifact_sha256=prepared["artifact_sha256"],
                    xml_package_sha256="summary-queued-hash",
                    validation_validator_id=prepared["validation_validator_id"],
                    validation_validator_version=prepared["validation_validator_version"],
                    validation_mode=prepared["validation_mode"],
                    validation_status=prepared["validation_status"],
                    validated_at=validated_at,
                    validated_by_user_id=prepared["validated_by_user_id"],
                ),
                PayrollT4SubmissionJob(
                    company_id=company_id,
                    tax_year=2026,
                    filing_artifact_id=prepared["filing_artifact_id"],
                    status="TRANSMISSION_RECORDED_MANUAL",
                    created_at=created_at + timedelta(minutes=3),
                    created_by_user_id=prepared["created_by_user_id"],
                    transmission_started_at=created_at + timedelta(minutes=4),
                    transmission_completed_at=created_at + timedelta(minutes=5),
                    transmission_reference="portal-upload-pending",
                    filing_artifact_sha256=prepared["artifact_sha256"],
                    xml_package_sha256="summary-pending-response-hash",
                    validation_validator_id=prepared["validation_validator_id"],
                    validation_validator_version=prepared["validation_validator_version"],
                    validation_mode=prepared["validation_mode"],
                    validation_status=prepared["validation_status"],
                    validated_at=validated_at,
                    validated_by_user_id=prepared["validated_by_user_id"],
                ),
                PayrollT4SubmissionJob(
                    company_id=company_id,
                    tax_year=2026,
                    filing_artifact_id=prepared["filing_artifact_id"],
                    status="RESPONSE_ACCEPTED_MANUAL",
                    created_at=created_at + timedelta(minutes=6),
                    created_by_user_id=prepared["created_by_user_id"],
                    transmission_started_at=created_at + timedelta(minutes=7),
                    transmission_completed_at=created_at + timedelta(minutes=8),
                    transmission_reference="portal-upload-accepted",
                    response_status="ACCEPTED",
                    response_recorded_at=created_at + timedelta(minutes=9),
                    response_recorded_by_user_id=prepared["created_by_user_id"],
                    response_message="Accepted for processing",
                    filing_artifact_sha256=prepared["artifact_sha256"],
                    xml_package_sha256="summary-accepted-hash",
                    validation_validator_id=prepared["validation_validator_id"],
                    validation_validator_version=prepared["validation_validator_version"],
                    validation_mode=prepared["validation_mode"],
                    validation_status=prepared["validation_status"],
                    validated_at=validated_at,
                    validated_by_user_id=prepared["validated_by_user_id"],
                ),
                PayrollT4SubmissionJob(
                    company_id=company_id,
                    tax_year=2026,
                    filing_artifact_id=prepared["filing_artifact_id"],
                    status="RESPONSE_REJECTED_MANUAL",
                    created_at=created_at + timedelta(minutes=10),
                    created_by_user_id=prepared["created_by_user_id"],
                    transmission_started_at=created_at + timedelta(minutes=11),
                    transmission_completed_at=created_at + timedelta(minutes=12),
                    transmission_reference="portal-upload-rejected",
                    response_status="REJECTED",
                    response_recorded_at=created_at + timedelta(minutes=13),
                    response_recorded_by_user_id=prepared["created_by_user_id"],
                    response_message="Slip count mismatch in uploaded package",
                    filing_artifact_sha256=prepared["artifact_sha256"],
                    xml_package_sha256="summary-rejected-hash",
                    validation_validator_id=prepared["validation_validator_id"],
                    validation_validator_version=prepared["validation_validator_version"],
                    validation_mode=prepared["validation_mode"],
                    validation_status=prepared["validation_status"],
                    validated_at=validated_at,
                    validated_by_user_id=prepared["validated_by_user_id"],
                ),
                PayrollT4SubmissionJob(
                    company_id=company_id,
                    tax_year=2026,
                    filing_artifact_id=prepared["filing_artifact_id"],
                    status="FAILED_MANUAL",
                    created_at=created_at + timedelta(minutes=14),
                    created_by_user_id=prepared["created_by_user_id"],
                    failure_message="Submission package blocked pending payroll manager review",
                    filing_artifact_sha256=prepared["artifact_sha256"],
                    xml_package_sha256="summary-failed-manual-hash",
                    validation_validator_id=prepared["validation_validator_id"],
                    validation_validator_version=prepared["validation_validator_version"],
                    validation_mode=prepared["validation_mode"],
                    validation_status=prepared["validation_status"],
                    validated_at=validated_at,
                    validated_by_user_id=prepared["validated_by_user_id"],
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    listed = client.get("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert listed.status_code == 200, listed.text
    body = listed.json()

    assert [row["status"] for row in body["rows"]] == [
        "FAILED_MANUAL",
        "RESPONSE_REJECTED_MANUAL",
        "RESPONSE_ACCEPTED_MANUAL",
        "TRANSMISSION_RECORDED_MANUAL",
        "PREPARED",
        "PREPARED",
    ]
    assert [row["workflow_stage"] for row in body["rows"]] == [
        "FAILED_MANUAL",
        "RESPONSE_REJECTED_MANUAL",
        "RESPONSE_ACCEPTED_MANUAL",
        "TRANSMITTED_MANUAL_PENDING_RESPONSE",
        "QUEUED_MANUAL_PENDING_TRANSMISSION",
        "PREPARED",
    ]
    assert body["summary"] == {
        "total": 6,
        "in_progress": 3,
        "accepted": 1,
        "rejected": 1,
        "failed_manual": 1,
        "actionable": 5,
        "queued_manual_pending_transmission": 1,
        "transmitted_manual_pending_response": 1,
        "terminal": 3,
    }


def test_t4_submission_job_history_returns_truthful_manual_timeline():
    company_id = 681133
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    queued = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/queue",
        headers=_owner_headers(company_id),
    )
    assert queued.status_code == 200, queued.text

    transmitted = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "portal-upload-history"},
    )
    assert transmitted.status_code == 200, transmitted.text

    responded = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "REJECTED",
            "response_reference": "cra-reject-history",
            "response_code": "SCHEMA_VALIDATION_FAILED",
            "response_message": "Slip count mismatch in uploaded package",
        },
    )
    assert responded.status_code == 200, responded.text

    history = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/history",
        headers=_owner_headers(company_id),
    )
    assert history.status_code == 200, history.text
    body = history.json()

    assert [row["action"] for row in body["rows"]] == [
        "CREATED",
        "QUEUED",
        "MANUAL_TRANSMISSION_RECORDED",
        "MANUAL_RESPONSE_REJECTED",
    ]
    assert body["rows"][0]["event_type"] == "payroll_t4_submission_job_created"
    assert body["rows"][0]["status"] == "PREPARED"
    assert body["rows"][0]["actor_user_id"] == f"owner-{company_id}"
    assert body["rows"][1]["event_type"] == "payroll_t4_submission_job_queued"
    assert body["rows"][1]["queued_at"] == queued.json()["queued_at"]
    assert body["rows"][2]["event_type"] == "payroll_t4_submission_job_manual_transmission_recorded"
    assert body["rows"][2]["transmission_reference"] == "portal-upload-history"
    assert body["rows"][3]["event_type"] == "payroll_t4_submission_job_manual_response_rejected"
    assert body["rows"][3]["response_status"] == "REJECTED"
    assert body["rows"][3]["response_reference"] == "cra-reject-history"
    assert body["rows"][3]["response_code"] == "SCHEMA_VALIDATION_FAILED"
    assert body["rows"][3]["response_message"] == "Slip count mismatch in uploaded package"
    assert body["rows"][3]["status"] == "RESPONSE_REJECTED_MANUAL"
    assert all(row["event_timestamp"] is not None for row in body["rows"])


def test_t4_submission_job_history_is_company_scoped():
    company_id = 681134
    other_company_id = 681135
    _prepare_ready_t4_submission_package(company_id=company_id)
    _prepare_ready_t4_submission_package(company_id=other_company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text

    history = client.get(
        f"/payroll/t4s/submission-jobs/{created.json()['id']}/history",
        headers=_owner_headers(other_company_id),
    )
    assert history.status_code == 404


def test_t4_submission_job_validation_result_returns_structured_internal_validation_snapshot():
    company_id = 681137
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text

    validation_result = client.get(
        f"/payroll/t4s/submission-jobs/{created.json()['id']}/validation-result",
        headers=_owner_headers(company_id),
    )
    assert validation_result.status_code == 200, validation_result.text
    body = validation_result.json()

    assert body["submission_job_id"] == created.json()["id"]
    assert body["tax_year"] == 2026
    assert body["filing_artifact_id"] == created.json()["filing_artifact_id"]
    assert body["artifact_hash"] == created.json()["artifact_sha256"]
    assert body["xml_package_sha256"] == created.json()["xml_package_sha256"]
    assert body["validation_status"] == created.json()["validation_status"]
    assert body["validation_timestamp"] == created.json()["validated_at"]
    assert body["validation_validator_id"] == created.json()["validation_validator_id"]
    assert body["validation_validator_version"] == created.json()["validation_validator_version"]
    assert body["validation_mode"] == created.json()["validation_mode"]
    assert body["validation_errors"] == []


def test_t4_submission_job_validation_result_is_company_scoped_and_rejects_stale_snapshot():
    company_id = 681138
    other_company_id = 681139
    _prepare_ready_t4_submission_package(company_id=company_id)
    _prepare_ready_t4_submission_package(company_id=other_company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    cross_company = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/validation-result",
        headers=_owner_headers(other_company_id),
    )
    assert cross_company.status_code == 404

    db = SessionLocal()
    try:
        artifact_row = (
            db.query(PayrollT4FilingArtifact)
            .filter(PayrollT4FilingArtifact.company_id == company_id)
            .filter(PayrollT4FilingArtifact.filing_artifact_id == created.json()["filing_artifact_id"])
            .one()
        )
        artifact_row.xml_validation_xml_sha256 = "stale-validation-hash"
        db.commit()
    finally:
        db.close()

    stale = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/validation-result",
        headers=_owner_headers(company_id),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "Submission job validation XML snapshot is stale"


def test_t4_submission_job_validation_result_rejects_stale_validator_metadata_snapshot():
    company_id = 681145
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    db = SessionLocal()
    try:
        artifact_row = (
            db.query(PayrollT4FilingArtifact)
            .filter(PayrollT4FilingArtifact.company_id == company_id)
            .filter(PayrollT4FilingArtifact.filing_artifact_id == created.json()["filing_artifact_id"])
            .one()
        )
        artifact_row.xml_validation_validator_version = "9.9"
        db.commit()
    finally:
        db.close()

    stale = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/validation-result",
        headers=_owner_headers(company_id),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "Submission job validation validator snapshot is stale"


def test_t4_submission_job_attempts_returns_truthful_attempt_history():
    company_id = 681140
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    attempts_prepared = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempts",
        headers=_owner_headers(company_id),
    )
    assert attempts_prepared.status_code == 200, attempts_prepared.text
    assert attempts_prepared.json()["submission_job_id"] == submission_job_id
    assert attempts_prepared.json()["final_outcome"] is None
    assert attempts_prepared.json()["final_outcome_detail"] is None
    assert attempts_prepared.json()["rows"] == [
        {
            "attempt_number": 1,
            "lifecycle_stage": "VALIDATED",
            "created_at": created.json()["created_at"],
            "validated_at": created.json()["validated_at"],
            "queued_at": None,
            "transmission_recorded_at": None,
            "response_recorded_at": None,
            "failure_recorded_at": None,
            "validation_passed": True,
            "outcome": "IN_PROGRESS",
            "response_outcome": None,
            "failure_reason": None,
        }
    ]

    queued = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/queue",
        headers=_owner_headers(company_id),
    )
    assert queued.status_code == 200, queued.text

    attempts_queued = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempts",
        headers=_owner_headers(company_id),
    )
    assert attempts_queued.status_code == 200, attempts_queued.text
    assert attempts_queued.json()["rows"][0]["lifecycle_stage"] == "QUEUED"
    assert attempts_queued.json()["rows"][0]["queued_at"] == queued.json()["queued_at"]

    transmitted = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "portal-attempt-history"},
    )
    assert transmitted.status_code == 200, transmitted.text

    responded = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "REJECTED",
            "response_reference": "cra-attempt-reject",
            "response_code": "SCHEMA_VALIDATION_FAILED",
            "response_message": "Slip count mismatch in uploaded package",
        },
    )
    assert responded.status_code == 200, responded.text

    attempts_responded = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempts",
        headers=_owner_headers(company_id),
    )
    assert attempts_responded.status_code == 200, attempts_responded.text
    assert attempts_responded.json()["final_outcome"] == "REJECTED"
    assert attempts_responded.json()["final_outcome_detail"] == "Slip count mismatch in uploaded package"
    assert attempts_responded.json()["rows"] == [
        {
            "attempt_number": 1,
            "lifecycle_stage": "RESPONSE_REJECTED",
            "created_at": created.json()["created_at"],
            "validated_at": created.json()["validated_at"],
            "queued_at": queued.json()["queued_at"],
            "transmission_recorded_at": transmitted.json()["transmission_completed_at"],
            "response_recorded_at": responded.json()["response_recorded_at"],
            "failure_recorded_at": None,
            "validation_passed": True,
            "outcome": "REJECTED",
            "response_outcome": "REJECTED",
            "failure_reason": None,
        }
    ]


def test_t4_submission_job_attempt_timeline_returns_unified_persisted_events():
    company_id = 681145
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    queued = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/queue",
        headers=_owner_headers(company_id),
    )
    assert queued.status_code == 200, queued.text

    transmitted = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "attempt-event-stream-001"},
    )
    assert transmitted.status_code == 200, transmitted.text

    rejected = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "REJECTED",
            "response_reference": "cra-reject-stream-001",
            "response_code": "SCHEMA_VALIDATION_FAILED",
            "response_message": "Slip count mismatch in uploaded package",
        },
    )
    assert rejected.status_code == 200, rejected.text

    retried = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/retry",
        headers=_owner_headers(company_id),
    )
    assert retried.status_code == 200, retried.text

    timeline = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempt-timeline",
        headers=_owner_headers(company_id),
    )
    assert timeline.status_code == 200, timeline.text
    body = timeline.json()

    assert body["submission_job_id"] == submission_job_id
    assert body["final_outcome"] is None
    assert body["final_outcome_detail"] is None
    assert [(row["attempt_number"], row["event_type"]) for row in body["rows"]] == [
        (1, "ATTEMPT_CREATED"),
        (1, "VALIDATION_COMPLETED"),
        (1, "QUEUED"),
        (1, "TRANSMISSION_RECORDED"),
        (1, "RESPONSE_REJECTED"),
        (1, "RETRIED"),
        (2, "ATTEMPT_CREATED"),
        (2, "VALIDATION_COMPLETED"),
    ]
    assert body["rows"][2]["queued_at"] == queued.json()["queued_at"]
    assert body["rows"][3]["transmission_reference"] == "attempt-event-stream-001"
    assert body["rows"][4]["response_status"] == "REJECTED"
    assert body["rows"][4]["response_code"] == "SCHEMA_VALIDATION_FAILED"
    assert body["rows"][5]["retried_to_attempt_number"] == 2
    assert body["rows"][7]["validated_at"] == retried.json()["validated_at"]

    db = SessionLocal()
    try:
        persisted_events = (
            db.query(PayrollT4SubmissionAttemptEvent)
            .filter(PayrollT4SubmissionAttemptEvent.company_id == company_id)
            .filter(PayrollT4SubmissionAttemptEvent.submission_job_id == submission_job_id)
            .order_by(
                PayrollT4SubmissionAttemptEvent.event_timestamp.asc(),
                PayrollT4SubmissionAttemptEvent.attempt_number.asc(),
                PayrollT4SubmissionAttemptEvent.id.asc(),
            )
            .all()
        )
        assert [(row.attempt_number, row.event_type) for row in persisted_events] == [
            (1, "ATTEMPT_CREATED"),
            (1, "VALIDATION_COMPLETED"),
            (1, "QUEUED"),
            (1, "TRANSMISSION_RECORDED"),
            (1, "RESPONSE_REJECTED"),
            (1, "RETRIED"),
            (2, "ATTEMPT_CREATED"),
            (2, "VALIDATION_COMPLETED"),
        ]
    finally:
        db.close()


def test_t4_submission_job_attempt_timeline_is_company_scoped_and_reports_failure():
    company_id = 681146
    other_company_id = 681147
    _prepare_ready_t4_submission_package(company_id=company_id)
    _prepare_ready_t4_submission_package(company_id=other_company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    failed = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": "MANUAL_REVIEW_BLOCKED",
            "failure_message": "Submission package blocked pending payroll manager review",
        },
    )
    assert failed.status_code == 200, failed.text

    cross_company = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempt-timeline",
        headers=_owner_headers(other_company_id),
    )
    assert cross_company.status_code == 404

    timeline = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempt-timeline",
        headers=_owner_headers(company_id),
    )
    assert timeline.status_code == 200, timeline.text
    assert [(row["attempt_number"], row["event_type"]) for row in timeline.json()["rows"]] == [
        (1, "ATTEMPT_CREATED"),
        (1, "VALIDATION_COMPLETED"),
        (1, "FAILURE_RECORDED"),
    ]
    assert timeline.json()["rows"][-1]["failure_code"] == "MANUAL_REVIEW_BLOCKED"
    assert timeline.json()["rows"][-1]["failure_reason"] == (
        "MANUAL_REVIEW_BLOCKED: Submission package blocked pending payroll manager review"
    )


def test_t4_submission_job_attempt_timeline_derives_terminal_outcome_when_persisted_snapshot_is_stale():
    company_id = 681148
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    transmitted = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "stale-outcome-transmission"},
    )
    assert transmitted.status_code == 200, transmitted.text

    rejected = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "REJECTED",
            "response_reference": "cra-reject-stale-outcome",
            "response_code": "SCHEMA_VALIDATION_FAILED",
            "response_message": "Slip count mismatch in uploaded package",
        },
    )
    assert rejected.status_code == 200, rejected.text

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        row.final_outcome = None
        row.final_outcome_detail = None
        db.commit()
    finally:
        db.close()

    timeline = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempt-timeline",
        headers=_owner_headers(company_id),
    )
    assert timeline.status_code == 200, timeline.text
    assert timeline.json()["final_outcome"] == "REJECTED"
    assert timeline.json()["final_outcome_detail"] == "Slip count mismatch in uploaded package"


def test_t4_submission_job_attempts_is_company_scoped_and_reports_manual_failure():
    company_id = 681141
    other_company_id = 681142
    _prepare_ready_t4_submission_package(company_id=company_id)
    _prepare_ready_t4_submission_package(company_id=other_company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    cross_company = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempts",
        headers=_owner_headers(other_company_id),
    )
    assert cross_company.status_code == 404

    failed = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": "MANUAL_REVIEW_BLOCKED",
            "failure_message": "Submission package blocked pending payroll manager review",
        },
    )
    assert failed.status_code == 200, failed.text

    attempts = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempts",
        headers=_owner_headers(company_id),
    )
    assert attempts.status_code == 200, attempts.text
    assert attempts.json()["final_outcome"] == "FAILED_MANUAL"
    assert attempts.json()["final_outcome_detail"] == "Submission package blocked pending payroll manager review"
    assert attempts.json()["rows"][0]["failure_recorded_at"] is not None
    assert attempts.json()["rows"] == [
        {
            "attempt_number": 1,
            "lifecycle_stage": "FAILURE_RECORDED",
            "created_at": created.json()["created_at"],
            "validated_at": created.json()["validated_at"],
            "queued_at": None,
            "transmission_recorded_at": None,
            "response_recorded_at": None,
            "failure_recorded_at": attempts.json()["rows"][0]["failure_recorded_at"],
            "validation_passed": True,
            "outcome": "FAILED_MANUAL",
            "response_outcome": "FAILED_MANUAL",
            "failure_reason": "MANUAL_REVIEW_BLOCKED: Submission package blocked pending payroll manager review",
        }
    ]


def test_t4_submission_job_attempts_derive_terminal_outcome_when_persisted_snapshot_is_stale():
    company_id = 681149
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    failed = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": "MANUAL_REVIEW_BLOCKED",
            "failure_message": "Submission package blocked pending payroll manager review",
        },
    )
    assert failed.status_code == 200, failed.text

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        row.final_outcome = None
        row.final_outcome_detail = None
        db.commit()
    finally:
        db.close()

    attempts = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempts",
        headers=_owner_headers(company_id),
    )
    assert attempts.status_code == 200, attempts.text
    assert attempts.json()["final_outcome"] == "FAILED_MANUAL"
    assert attempts.json()["final_outcome_detail"] == "Submission package blocked pending payroll manager review"


def test_t4_submission_job_create_persists_initial_submission_attempt_and_idempotent_retry_does_not_duplicate():
    company_id = 681136
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text

    created_again = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created_again.status_code == 200, created_again.text
    assert created_again.json()["id"] == created.json()["id"]

    db = SessionLocal()
    try:
        attempts = (
            db.query(PayrollT4SubmissionAttempt)
            .filter(PayrollT4SubmissionAttempt.company_id == company_id)
            .filter(PayrollT4SubmissionAttempt.submission_job_id == created.json()["id"])
            .order_by(PayrollT4SubmissionAttempt.attempt_number.asc())
            .all()
        )
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].lifecycle_state == "VALIDATED"
        assert attempts[0].validation_passed is True
        assert attempts[0].validated_at is not None
        assert attempts[0].queued_at is None
        assert attempts[0].transmission_recorded_at is None
        assert attempts[0].response_recorded_at is None
        assert attempts[0].failure_recorded_at is None
        assert attempts[0].response_outcome is None
        assert attempts[0].failure_reason is None
        assert attempts[0].created_at.astimezone(timezone.utc).isoformat() == created.json()["created_at"]
    finally:
        db.close()


def test_t4_submission_job_manual_transmission_recording_is_truthful_and_idempotent():
    company_id = 681116
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-001"},
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()

    assert body["status"] == "TRANSMISSION_RECORDED_MANUAL"
    assert body["workflow_mode"] == "MANUAL_ONLY"
    assert body["workflow_stage"] == "TRANSMITTED_MANUAL_PENDING_RESPONSE"
    assert body["next_expected_action"] == "RECORD_MANUAL_RESPONSE_OR_FAILURE"
    assert body["allowed_actions"] == ["RECORD_MANUAL_RESPONSE", "RECORD_MANUAL_FAILURE"]
    assert body["blocked_actions"] == {
        "QUEUE": "Submission job can only be queued from PREPARED status",
        "RETRY": "Submission job can only be retried from FAILED_MANUAL or RESPONSE_REJECTED_MANUAL status",
        "RECORD_MANUAL_TRANSMISSION": "Manual transmission already recorded for this submission job",
    }
    assert body["terminal_outcome"] == "IN_PROGRESS"
    assert body["terminal_outcome_detail"] is None
    assert body["final_outcome"] is None
    assert body["final_outcome_detail"] is None
    assert body["can_queue"] is False
    assert body["can_retry"] is False
    assert body["can_record_manual_transmission"] is False
    assert body["can_record_manual_response"] is True
    assert body["can_record_manual_failure"] is True
    assert body["transmission_reference"] == "manual-cra-drop-001"
    assert body["transmission_started_at"] is not None
    assert body["transmission_completed_at"] is not None
    assert body["queued_at"] is None
    assert body["validation_status"] == "VALID"

    recorded_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-001"},
    )
    assert recorded_again.status_code == 200, recorded_again.text
    assert recorded_again.json() == body

    db = SessionLocal()
    try:
        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_manual_transmission_recorded")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payload_json["submission_job_id"] == submission_job_id
        assert audit_events[0].payload_json["status"] == "TRANSMISSION_RECORDED_MANUAL"
        assert audit_events[0].payload_json["transmission_reference"] == "manual-cra-drop-001"
        assert audit_events[0].payload_json["actor_user_id"] == f"owner-{company_id}"
        assert audit_events[0].payload_json["artifact_sha256"] == body["artifact_sha256"]
        assert audit_events[0].payload_json["xml_hash"] == body["xml_package_sha256"]
        assert audit_events[0].payload_json["xml_package_sha256"] == body["xml_package_sha256"]
        assert audit_events[0].payload_json["validation_validator_id"] == body["validation_validator_id"]
        assert audit_events[0].payload_json["validation_validator_version"] == body["validation_validator_version"]
        assert audit_events[0].payload_json["validation_mode"] == body["validation_mode"]
        assert audit_events[0].payload_json["validation_status"] == body["validation_status"]
        assert audit_events[0].payload_json["validated_at"] == body["validated_at"]
        assert audit_events[0].payload_json["validated_by_user_id"] == body["validated_by_user_id"]
    finally:
        db.close()

    db = SessionLocal()
    try:
        attempts = (
            db.query(PayrollT4SubmissionAttempt)
            .filter(PayrollT4SubmissionAttempt.company_id == company_id)
            .filter(PayrollT4SubmissionAttempt.submission_job_id == submission_job_id)
            .all()
        )
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].lifecycle_state == "TRANSMISSION_RECORDED"
        assert attempts[0].validation_passed is True
        assert attempts[0].validated_at is not None
        assert attempts[0].queued_at is not None
        assert attempts[0].transmission_recorded_at is not None
        assert attempts[0].response_recorded_at is None
        assert attempts[0].failure_recorded_at is None
        assert attempts[0].response_outcome is None
        assert attempts[0].failure_reason is None
    finally:
        db.close()

    attempts_response = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempts",
        headers=_owner_headers(company_id),
    )
    assert attempts_response.status_code == 200, attempts_response.text
    assert attempts_response.json()["rows"] == [
        {
            "attempt_number": 1,
            "lifecycle_stage": "TRANSMISSION_RECORDED",
            "created_at": created.json()["created_at"],
            "validated_at": created.json()["validated_at"],
            "queued_at": body["transmission_completed_at"],
            "transmission_recorded_at": body["transmission_completed_at"],
            "response_recorded_at": None,
            "failure_recorded_at": None,
            "validation_passed": True,
            "outcome": "IN_PROGRESS",
            "response_outcome": None,
            "failure_reason": None,
        }
    ]


def test_t4_submission_job_manual_transmission_trims_request_payload_for_idempotency():
    company_id = 681117
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": " manual-cra-drop-001 "},
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()

    assert body["transmission_reference"] == "manual-cra-drop-001"

    recorded_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-001"},
    )
    assert recorded_again.status_code == 200, recorded_again.text
    assert recorded_again.json() == body


def test_t4_submission_job_manual_transmission_idempotent_retry_repairs_persisted_validation_snapshot_fields():
    company_id = 681118
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-001b"},
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        row.filing_artifact_sha256 = f" {body['artifact_sha256']} "
        row.xml_package_sha256 = f" {body['xml_package_sha256']} "
        row.validation_validator_id = f" {body['validation_validator_id']} "
        row.validation_validator_version = f" {body['validation_validator_version']} "
        row.validated_by_user_id = f" {body['validated_by_user_id']} "
        row.validated_at = row.validated_at.replace(tzinfo=None)
        db.commit()
    finally:
        db.close()

    recorded_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-001b"},
    )
    assert recorded_again.status_code == 200, recorded_again.text

    repaired_body = recorded_again.json()
    assert repaired_body["id"] == body["id"]
    assert repaired_body["transmission_reference"] == body["transmission_reference"]
    assert repaired_body["artifact_sha256"] == body["artifact_sha256"]
    assert repaired_body["xml_package_sha256"] == body["xml_package_sha256"]
    assert repaired_body["validation_validator_id"] == body["validation_validator_id"]
    assert repaired_body["validation_validator_version"] == body["validation_validator_version"]
    assert repaired_body["validated_at"] == body["validated_at"]
    assert repaired_body["validated_by_user_id"] == body["validated_by_user_id"]

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        assert row.filing_artifact_sha256 == body["artifact_sha256"]
        assert row.xml_package_sha256 == body["xml_package_sha256"]
        assert row.validation_validator_id == body["validation_validator_id"]
        assert row.validation_validator_version == body["validation_validator_version"]
        assert row.validated_by_user_id == body["validated_by_user_id"]
        assert row.validated_at.astimezone(timezone.utc).isoformat() == body["validated_at"]

        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_manual_transmission_recorded")
            .all()
        )
        assert len(audit_events) == 1
    finally:
        db.close()


def test_t4_submission_job_manual_response_recording_is_truthful_and_idempotent():
    company_id = 681122
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded_transmission = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-accepted-001"},
    )
    assert recorded_transmission.status_code == 200, recorded_transmission.text

    recorded_response = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "ACCEPTED",
            "response_reference": "cra-ack-accepted-001",
            "response_message": "Accepted for processing",
        },
    )
    assert recorded_response.status_code == 200, recorded_response.text
    body = recorded_response.json()

    assert body["status"] == "RESPONSE_ACCEPTED_MANUAL"
    assert body["workflow_mode"] == "MANUAL_ONLY"
    assert body["workflow_stage"] == "RESPONSE_ACCEPTED_MANUAL"
    assert body["next_expected_action"] == "NONE"
    assert body["allowed_actions"] == []
    assert body["blocked_actions"] == {
        "QUEUE": "Submission job can only be queued from PREPARED status",
        "RETRY": "Submission job can only be retried from FAILED_MANUAL or RESPONSE_REJECTED_MANUAL status",
        "RECORD_MANUAL_TRANSMISSION": "Manual transmission can only be recorded from PREPARED status",
        "RECORD_MANUAL_RESPONSE": "CRA response already recorded for this submission job",
        "RECORD_MANUAL_FAILURE": "Manual failure cannot be recorded after CRA response is recorded",
    }
    assert body["terminal_outcome"] == "ACCEPTED"
    assert body["terminal_outcome_detail"] == "Accepted for processing"
    assert body["final_outcome"] == "ACCEPTED"
    assert body["final_outcome_detail"] == "Accepted for processing"
    assert body["can_queue"] is False
    assert body["can_retry"] is False
    assert body["can_record_manual_transmission"] is False
    assert body["can_record_manual_response"] is False
    assert body["can_record_manual_failure"] is False
    assert body["response_status"] == "ACCEPTED"
    assert body["response_recorded_at"] is not None
    assert body["response_recorded_by_user_id"] == f"owner-{company_id}"
    assert body["response_reference"] == "cra-ack-accepted-001"
    assert body["response_code"] is None
    assert body["response_message"] == "Accepted for processing"
    assert body["transmission_reference"] == "manual-cra-drop-accepted-001"

    recorded_response_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "ACCEPTED",
            "response_reference": "cra-ack-accepted-001",
            "response_message": "Accepted for processing",
        },
    )
    assert recorded_response_again.status_code == 200, recorded_response_again.text
    assert recorded_response_again.json() == body

    db = SessionLocal()
    try:
        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_manual_response_accepted")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payload_json["submission_job_id"] == submission_job_id
        assert audit_events[0].payload_json["status"] == "RESPONSE_ACCEPTED_MANUAL"
        assert audit_events[0].payload_json["response_status"] == "ACCEPTED"
        assert audit_events[0].payload_json["response_reference"] == "cra-ack-accepted-001"
        assert audit_events[0].payload_json["response_message"] == "Accepted for processing"
        assert audit_events[0].payload_json["actor_user_id"] == f"owner-{company_id}"
        assert audit_events[0].payload_json["validation_validator_id"] == body["validation_validator_id"]
        assert audit_events[0].payload_json["validation_validator_version"] == body["validation_validator_version"]
        assert audit_events[0].payload_json["validation_mode"] == body["validation_mode"]
        assert audit_events[0].payload_json["validation_status"] == body["validation_status"]
        assert audit_events[0].payload_json["validated_at"] == body["validated_at"]
        assert audit_events[0].payload_json["validated_by_user_id"] == body["validated_by_user_id"]
    finally:
        db.close()

    db = SessionLocal()
    try:
        attempts = (
            db.query(PayrollT4SubmissionAttempt)
            .filter(PayrollT4SubmissionAttempt.company_id == company_id)
            .filter(PayrollT4SubmissionAttempt.submission_job_id == submission_job_id)
            .all()
        )
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].lifecycle_state == "RESPONSE_ACCEPTED"
        assert attempts[0].validation_passed is True
        assert attempts[0].validated_at is not None
        assert attempts[0].queued_at is not None
        assert attempts[0].transmission_recorded_at is not None
        assert attempts[0].response_recorded_at is not None
        assert attempts[0].failure_recorded_at is None
        assert attempts[0].response_outcome == "ACCEPTED"
        assert attempts[0].failure_reason is None
    finally:
        db.close()


def test_t4_submission_job_manual_response_trims_and_canonicalizes_request_payload():
    company_id = 681131
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded_transmission = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-accepted-002"},
    )
    assert recorded_transmission.status_code == 200, recorded_transmission.text

    recorded_response = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": " accepted ",
            "response_reference": " cra-ack-accepted-002 ",
            "response_message": " Accepted for processing ",
        },
    )
    assert recorded_response.status_code == 200, recorded_response.text
    body = recorded_response.json()

    assert body["response_status"] == "ACCEPTED"
    assert body["response_reference"] == "cra-ack-accepted-002"
    assert body["response_message"] == "Accepted for processing"

    recorded_response_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "ACCEPTED",
            "response_reference": "cra-ack-accepted-002",
            "response_message": "Accepted for processing",
        },
    )
    assert recorded_response_again.status_code == 200, recorded_response_again.text
    assert recorded_response_again.json() == body


def test_t4_submission_job_manual_response_idempotent_retry_repairs_persisted_response_recorded_by_user_id():
    company_id = 681133
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded_transmission = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-accepted-003"},
    )
    assert recorded_transmission.status_code == 200, recorded_transmission.text

    recorded_response = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "ACCEPTED",
            "response_reference": "cra-ack-accepted-003",
            "response_message": "Accepted for processing",
        },
    )
    assert recorded_response.status_code == 200, recorded_response.text
    body = recorded_response.json()

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        row.response_recorded_by_user_id = f" owner-{company_id} "
        db.commit()
    finally:
        db.close()

    recorded_response_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "ACCEPTED",
            "response_reference": "cra-ack-accepted-003",
            "response_message": "Accepted for processing",
        },
    )
    assert recorded_response_again.status_code == 200, recorded_response_again.text

    repaired_body = recorded_response_again.json()
    assert repaired_body["id"] == body["id"]
    assert repaired_body["status"] == body["status"]
    assert repaired_body["response_recorded_at"] == body["response_recorded_at"]
    assert repaired_body["response_reference"] == body["response_reference"]
    assert repaired_body["response_message"] == body["response_message"]
    assert repaired_body["response_recorded_by_user_id"] == f"owner-{company_id}"

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        assert row.response_recorded_by_user_id == f"owner-{company_id}"

        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_manual_response_accepted")
            .all()
        )
        assert len(audit_events) == 1
    finally:
        db.close()


def test_t4_submission_job_manual_response_idempotent_retry_repairs_persisted_validation_snapshot_fields():
    company_id = 681134
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded_transmission = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-accepted-004"},
    )
    assert recorded_transmission.status_code == 200, recorded_transmission.text

    recorded_response = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "ACCEPTED",
            "response_reference": "cra-ack-accepted-004",
            "response_message": "Accepted for processing",
        },
    )
    assert recorded_response.status_code == 200, recorded_response.text
    body = recorded_response.json()

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        row.filing_artifact_sha256 = f" {body['artifact_sha256']} "
        row.xml_package_sha256 = f" {body['xml_package_sha256']} "
        row.validation_validator_id = f" {body['validation_validator_id']} "
        row.validation_validator_version = f" {body['validation_validator_version']} "
        row.validated_by_user_id = f" {body['validated_by_user_id']} "
        row.validated_at = row.validated_at.replace(tzinfo=None)
        db.commit()
    finally:
        db.close()

    recorded_response_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "ACCEPTED",
            "response_reference": "cra-ack-accepted-004",
            "response_message": "Accepted for processing",
        },
    )
    assert recorded_response_again.status_code == 200, recorded_response_again.text

    repaired_body = recorded_response_again.json()
    assert repaired_body["id"] == body["id"]
    assert repaired_body["artifact_sha256"] == body["artifact_sha256"]
    assert repaired_body["xml_package_sha256"] == body["xml_package_sha256"]
    assert repaired_body["validation_validator_id"] == body["validation_validator_id"]
    assert repaired_body["validation_validator_version"] == body["validation_validator_version"]
    assert repaired_body["validation_mode"] == body["validation_mode"]
    assert repaired_body["validation_status"] == body["validation_status"]
    assert repaired_body["validated_at"] == body["validated_at"]
    assert repaired_body["validated_by_user_id"] == body["validated_by_user_id"]

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        assert row.filing_artifact_sha256 == body["artifact_sha256"]
        assert row.xml_package_sha256 == body["xml_package_sha256"]
        assert row.validation_validator_id == body["validation_validator_id"]
        assert row.validation_validator_version == body["validation_validator_version"]
        assert row.validation_mode == body["validation_mode"]
        assert row.validation_status == body["validation_status"]
        assert row.validated_by_user_id == body["validated_by_user_id"]
        assert row.validated_at.astimezone(timezone.utc).isoformat() == body["validated_at"]

        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_manual_response_accepted")
            .all()
        )
        assert len(audit_events) == 1
    finally:
        db.close()


def test_t4_submission_job_manual_response_requires_recorded_transmission_and_rejection_metadata():
    company_id = 681123
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    before_transmission = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={"response_status": "ACCEPTED", "response_reference": "too-early"},
    )
    assert before_transmission.status_code == 409
    assert before_transmission.json()["detail"] == "CRA response can only be recorded after transmission is recorded"

    recorded_transmission = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-rejected-001"},
    )
    assert recorded_transmission.status_code == 200, recorded_transmission.text

    rejected_without_reason = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={"response_status": "REJECTED", "response_reference": "cra-reject-001"},
    )
    assert rejected_without_reason.status_code == 409
    assert rejected_without_reason.json()["detail"] == "Rejected responses require response_code or response_message"


def test_t4_submission_job_manual_rejected_response_is_truthful_idempotent_and_company_scoped():
    company_id = 681124
    other_company_id = 681125
    _prepare_ready_t4_submission_package(company_id=company_id)
    _prepare_ready_t4_submission_package(company_id=other_company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded_transmission = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-rejected-002"},
    )
    assert recorded_transmission.status_code == 200, recorded_transmission.text

    cross_company = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(other_company_id),
        json={
            "response_status": "REJECTED",
            "response_reference": "cra-reject-002",
            "response_code": "SCHEMA_VALIDATION_FAILED",
        },
    )
    assert cross_company.status_code == 404

    recorded_response = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "REJECTED",
            "response_reference": "cra-reject-002",
            "response_code": "SCHEMA_VALIDATION_FAILED",
            "response_message": "Slip count mismatch in uploaded package",
        },
    )
    assert recorded_response.status_code == 200, recorded_response.text
    body = recorded_response.json()

    assert body["status"] == "RESPONSE_REJECTED_MANUAL"
    assert body["terminal_outcome"] == "REJECTED"
    assert body["terminal_outcome_detail"] == "Slip count mismatch in uploaded package"
    assert body["final_outcome"] == "REJECTED"
    assert body["final_outcome_detail"] == "Slip count mismatch in uploaded package"
    assert body["response_status"] == "REJECTED"
    assert body["response_recorded_at"] is not None
    assert body["response_recorded_by_user_id"] == f"owner-{company_id}"
    assert body["response_reference"] == "cra-reject-002"
    assert body["response_code"] == "SCHEMA_VALIDATION_FAILED"
    assert body["response_message"] == "Slip count mismatch in uploaded package"

    recorded_response_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "REJECTED",
            "response_reference": "cra-reject-002",
            "response_code": "SCHEMA_VALIDATION_FAILED",
            "response_message": "Slip count mismatch in uploaded package",
        },
    )
    assert recorded_response_again.status_code == 200, recorded_response_again.text
    assert recorded_response_again.json() == body

    detail = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}",
        headers=_owner_headers(company_id),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["response_status"] == "REJECTED"
    assert detail.json()["response_code"] == "SCHEMA_VALIDATION_FAILED"
    assert detail.json()["response_message"] == "Slip count mismatch in uploaded package"

    db = SessionLocal()
    try:
        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_manual_response_rejected")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payload_json["submission_job_id"] == submission_job_id
        assert audit_events[0].payload_json["status"] == "RESPONSE_REJECTED_MANUAL"
        assert audit_events[0].payload_json["response_status"] == "REJECTED"
        assert audit_events[0].payload_json["response_reference"] == "cra-reject-002"
        assert audit_events[0].payload_json["response_code"] == "SCHEMA_VALIDATION_FAILED"
        assert audit_events[0].payload_json["response_message"] == "Slip count mismatch in uploaded package"
        assert audit_events[0].payload_json["actor_user_id"] == f"owner-{company_id}"
        assert audit_events[0].payload_json["validation_validator_id"] == body["validation_validator_id"]
        assert audit_events[0].payload_json["validation_validator_version"] == body["validation_validator_version"]
        assert audit_events[0].payload_json["validation_mode"] == body["validation_mode"]
        assert audit_events[0].payload_json["validation_status"] == body["validation_status"]
        assert audit_events[0].payload_json["validated_at"] == body["validated_at"]
        assert audit_events[0].payload_json["validated_by_user_id"] == body["validated_by_user_id"]
    finally:
        db.close()


def test_t4_submission_job_manual_failure_recording_is_truthful_idempotent_and_company_scoped():
    company_id = 681126
    other_company_id = 681127
    _prepare_ready_t4_submission_package(company_id=company_id)
    _prepare_ready_t4_submission_package(company_id=other_company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    cross_company = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(other_company_id),
        json={"failure_code": "MANUAL_REVIEW_BLOCKED"},
    )
    assert cross_company.status_code == 404

    recorded = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": "MANUAL_REVIEW_BLOCKED",
            "failure_message": "Submission package blocked pending payroll manager review",
        },
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()

    assert body["status"] == "FAILED_MANUAL"
    assert body["workflow_mode"] == "MANUAL_ONLY"
    assert body["workflow_stage"] == "FAILED_MANUAL"
    assert body["next_expected_action"] == "RETRY"
    assert body["allowed_actions"] == ["RETRY"]
    assert body["blocked_actions"] == {
        "QUEUE": "Submission job can only be queued from PREPARED status",
        "RECORD_MANUAL_TRANSMISSION": "Manual transmission can only be recorded from PREPARED status",
        "RECORD_MANUAL_RESPONSE": "CRA response can only be recorded after transmission is recorded",
        "RECORD_MANUAL_FAILURE": "Manual failure already recorded for this submission job",
    }
    assert body["terminal_outcome"] == "FAILED_MANUAL"
    assert body["terminal_outcome_detail"] == "Submission package blocked pending payroll manager review"
    assert body["final_outcome"] == "FAILED_MANUAL"
    assert body["final_outcome_detail"] == "Submission package blocked pending payroll manager review"
    assert body["can_queue"] is False
    assert body["can_retry"] is True
    assert body["can_record_manual_transmission"] is False
    assert body["can_record_manual_response"] is False
    assert body["can_record_manual_failure"] is False
    assert body["failure_code"] == "MANUAL_REVIEW_BLOCKED"
    assert body["failure_message"] == "Submission package blocked pending payroll manager review"
    assert body["response_status"] is None
    assert body["response_recorded_at"] is None
    assert body["transmission_reference"] is None

    recorded_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": "MANUAL_REVIEW_BLOCKED",
            "failure_message": "Submission package blocked pending payroll manager review",
        },
    )
    assert recorded_again.status_code == 200, recorded_again.text
    assert recorded_again.json() == body

    db = SessionLocal()
    try:
        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_manual_failure_recorded")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payload_json["submission_job_id"] == submission_job_id
        assert audit_events[0].payload_json["status"] == "FAILED_MANUAL"
        assert audit_events[0].payload_json["failure_code"] == "MANUAL_REVIEW_BLOCKED"
        assert audit_events[0].payload_json["failure_message"] == "Submission package blocked pending payroll manager review"
        assert audit_events[0].payload_json["actor_user_id"] == f"owner-{company_id}"
        assert audit_events[0].payload_json["validation_validator_id"] == body["validation_validator_id"]
        assert audit_events[0].payload_json["validation_validator_version"] == body["validation_validator_version"]
        assert audit_events[0].payload_json["validation_mode"] == body["validation_mode"]
        assert audit_events[0].payload_json["validation_status"] == body["validation_status"]
        assert audit_events[0].payload_json["validated_at"] == body["validated_at"]
        assert audit_events[0].payload_json["validated_by_user_id"] == body["validated_by_user_id"]
    finally:
        db.close()

    db = SessionLocal()
    try:
        attempts = (
            db.query(PayrollT4SubmissionAttempt)
            .filter(PayrollT4SubmissionAttempt.company_id == company_id)
            .filter(PayrollT4SubmissionAttempt.submission_job_id == submission_job_id)
            .all()
        )
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].lifecycle_state == "FAILURE_RECORDED"
        assert attempts[0].validation_passed is True
        assert attempts[0].validated_at is not None
        assert attempts[0].transmission_recorded_at is None
        assert attempts[0].response_recorded_at is None
        assert attempts[0].failure_recorded_at is not None
        assert attempts[0].response_outcome == "FAILED_MANUAL"
        assert attempts[0].failure_reason == "MANUAL_REVIEW_BLOCKED: Submission package blocked pending payroll manager review"
    finally:
        db.close()


def test_t4_submission_job_manual_failure_trims_request_payload_for_idempotency():
    company_id = 681132
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": " MANUAL_REVIEW_BLOCKED ",
            "failure_message": " Submission package blocked pending payroll manager review ",
        },
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()

    assert body["failure_code"] == "MANUAL_REVIEW_BLOCKED"
    assert body["failure_message"] == "Submission package blocked pending payroll manager review"

    recorded_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": "MANUAL_REVIEW_BLOCKED",
            "failure_message": "Submission package blocked pending payroll manager review",
        },
    )
    assert recorded_again.status_code == 200, recorded_again.text
    assert recorded_again.json() == body


def test_t4_submission_job_manual_failure_idempotent_retry_repairs_persisted_validation_snapshot_fields():
    company_id = 681135
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": "MANUAL_REVIEW_BLOCKED",
            "failure_message": "Submission package blocked pending payroll manager review",
        },
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        row.filing_artifact_sha256 = f" {body['artifact_sha256']} "
        row.xml_package_sha256 = f" {body['xml_package_sha256']} "
        row.validation_validator_id = f" {body['validation_validator_id']} "
        row.validation_validator_version = f" {body['validation_validator_version']} "
        row.validated_by_user_id = f" {body['validated_by_user_id']} "
        row.validated_at = row.validated_at.replace(tzinfo=None)
        db.commit()
    finally:
        db.close()

    recorded_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": "MANUAL_REVIEW_BLOCKED",
            "failure_message": "Submission package blocked pending payroll manager review",
        },
    )
    assert recorded_again.status_code == 200, recorded_again.text

    repaired_body = recorded_again.json()
    assert repaired_body["id"] == body["id"]
    assert repaired_body["artifact_sha256"] == body["artifact_sha256"]
    assert repaired_body["xml_package_sha256"] == body["xml_package_sha256"]
    assert repaired_body["validation_validator_id"] == body["validation_validator_id"]
    assert repaired_body["validation_validator_version"] == body["validation_validator_version"]
    assert repaired_body["validation_mode"] == body["validation_mode"]
    assert repaired_body["validation_status"] == body["validation_status"]
    assert repaired_body["validated_at"] == body["validated_at"]
    assert repaired_body["validated_by_user_id"] == body["validated_by_user_id"]

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        assert row.filing_artifact_sha256 == body["artifact_sha256"]
        assert row.xml_package_sha256 == body["xml_package_sha256"]
        assert row.validation_validator_id == body["validation_validator_id"]
        assert row.validation_validator_version == body["validation_validator_version"]
        assert row.validation_mode == body["validation_mode"]
        assert row.validation_status == body["validation_status"]
        assert row.validated_by_user_id == body["validated_by_user_id"]
        assert row.validated_at.astimezone(timezone.utc).isoformat() == body["validated_at"]

        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_manual_failure_recorded")
            .all()
        )
        assert len(audit_events) == 1
    finally:
        db.close()


def test_t4_submission_job_retry_after_manual_failure_spawns_new_attempt_idempotently():
    company_id = 681143
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    failed = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={
            "failure_code": "MANUAL_REVIEW_BLOCKED",
            "failure_message": "Submission package blocked pending payroll manager review",
        },
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["can_retry"] is True

    retried = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/retry",
        headers=_owner_headers(company_id),
    )
    assert retried.status_code == 200, retried.text
    body = retried.json()

    assert body["status"] == "PREPARED"
    assert body["workflow_stage"] == "PREPARED"
    assert body["next_expected_action"] == "QUEUE_OR_RECORD_MANUAL_TRANSMISSION"
    assert body["queued_at"] is None
    assert body["transmission_reference"] is None
    assert body["response_status"] is None
    assert body["failure_code"] is None
    assert body["failure_message"] is None
    assert body["can_retry"] is False
    assert body["final_outcome"] is None
    assert body["final_outcome_detail"] is None

    retried_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/retry",
        headers=_owner_headers(company_id),
    )
    assert retried_again.status_code == 200, retried_again.text
    assert retried_again.json() == body

    attempts = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempts",
        headers=_owner_headers(company_id),
    )
    assert attempts.status_code == 200, attempts.text
    assert attempts.json()["final_outcome"] is None
    assert attempts.json()["final_outcome_detail"] is None
    assert attempts.json()["rows"] == [
        {
            "attempt_number": 1,
            "lifecycle_stage": "FAILURE_RECORDED",
            "created_at": created.json()["created_at"],
            "validated_at": created.json()["validated_at"],
            "queued_at": None,
            "transmission_recorded_at": None,
            "response_recorded_at": None,
            "failure_recorded_at": attempts.json()["rows"][0]["failure_recorded_at"],
            "validation_passed": True,
            "outcome": "FAILED_MANUAL",
            "response_outcome": "FAILED_MANUAL",
            "failure_reason": "MANUAL_REVIEW_BLOCKED: Submission package blocked pending payroll manager review",
        },
        {
            "attempt_number": 2,
            "lifecycle_stage": "VALIDATED",
            "created_at": attempts.json()["rows"][1]["created_at"],
            "validated_at": body["validated_at"],
            "queued_at": None,
            "transmission_recorded_at": None,
            "response_recorded_at": None,
            "failure_recorded_at": None,
            "validation_passed": True,
            "outcome": "IN_PROGRESS",
            "response_outcome": None,
            "failure_reason": None,
        },
    ]

    history = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/history",
        headers=_owner_headers(company_id),
    )
    assert history.status_code == 200, history.text
    assert history.json()["rows"][-1]["event_type"] == "payroll_t4_submission_job_retried"
    assert history.json()["rows"][-1]["action"] == "RETRIED"

    db = SessionLocal()
    try:
        attempts_rows = (
            db.query(PayrollT4SubmissionAttempt)
            .filter(PayrollT4SubmissionAttempt.company_id == company_id)
            .filter(PayrollT4SubmissionAttempt.submission_job_id == submission_job_id)
            .order_by(PayrollT4SubmissionAttempt.attempt_number.asc())
            .all()
        )
        assert len(attempts_rows) == 2
        assert attempts_rows[0].attempt_number == 1
        assert attempts_rows[0].lifecycle_state == "FAILURE_RECORDED"
        assert attempts_rows[1].attempt_number == 2
        assert attempts_rows[1].lifecycle_state == "VALIDATED"
    finally:
        db.close()


def test_t4_submission_job_retry_after_rejected_response_preserves_attempt_history():
    company_id = 681144
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    transmitted = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "retry-rejected-transmission"},
    )
    assert transmitted.status_code == 200, transmitted.text

    rejected = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "REJECTED",
            "response_reference": "cra-reject-retry-001",
            "response_code": "SCHEMA_VALIDATION_FAILED",
            "response_message": "Slip count mismatch in uploaded package",
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["terminal_outcome"] == "REJECTED"
    assert rejected.json()["can_retry"] is True

    retried = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/retry",
        headers=_owner_headers(company_id),
    )
    assert retried.status_code == 200, retried.text
    body = retried.json()

    assert body["status"] == "PREPARED"
    assert body["queued_at"] is None
    assert body["transmission_started_at"] is None
    assert body["transmission_completed_at"] is None
    assert body["response_recorded_at"] is None
    assert body["response_reference"] is None
    assert body["response_code"] is None
    assert body["response_message"] is None
    assert body["final_outcome"] is None
    assert body["final_outcome_detail"] is None

    attempts = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/attempts",
        headers=_owner_headers(company_id),
    )
    assert attempts.status_code == 200, attempts.text
    assert attempts.json()["final_outcome"] is None
    assert attempts.json()["final_outcome_detail"] is None
    assert [row["attempt_number"] for row in attempts.json()["rows"]] == [1, 2]
    assert attempts.json()["rows"][0]["lifecycle_stage"] == "RESPONSE_REJECTED"
    assert attempts.json()["rows"][0]["response_outcome"] == "REJECTED"
    assert attempts.json()["rows"][1]["lifecycle_stage"] == "VALIDATED"
    assert attempts.json()["rows"][1]["response_outcome"] is None

def test_t4_submission_job_manual_failure_rejects_blank_payload_and_post_response_transition():
    company_id = 681128
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    blank_failure = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={},
    )
    assert blank_failure.status_code == 409
    assert blank_failure.json()["detail"] == "failure_code or failure_message is required"

    recorded_transmission = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-transmission",
        headers=_owner_headers(company_id),
        json={"transmission_reference": "manual-cra-drop-response-003"},
    )
    assert recorded_transmission.status_code == 200, recorded_transmission.text

    recorded_response = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-response",
        headers=_owner_headers(company_id),
        json={
            "response_status": "ACCEPTED",
            "response_reference": "cra-ack-003",
            "response_message": "Accepted for processing",
        },
    )
    assert recorded_response.status_code == 200, recorded_response.text

    after_response = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={"failure_code": "LATE_FAILURE"},
    )
    assert after_response.status_code == 409
    assert after_response.json()["detail"] == "Manual failure cannot be recorded after CRA response is recorded"


def test_t4_submission_job_queue_recording_is_truthful_idempotent_and_company_scoped():
    company_id = 681129
    other_company_id = 681130
    _prepare_ready_t4_submission_package(company_id=company_id)
    _prepare_ready_t4_submission_package(company_id=other_company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]
    assert created.json()["queued_at"] is None

    cross_company = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/queue",
        headers=_owner_headers(other_company_id),
    )
    assert cross_company.status_code == 404

    queued = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/queue",
        headers=_owner_headers(company_id),
    )
    assert queued.status_code == 200, queued.text
    body = queued.json()

    assert body["status"] == "PREPARED"
    assert body["workflow_mode"] == "MANUAL_ONLY"
    assert body["workflow_stage"] == "QUEUED_MANUAL_PENDING_TRANSMISSION"
    assert body["next_expected_action"] == "RECORD_MANUAL_TRANSMISSION"
    assert body["allowed_actions"] == ["QUEUE", "RECORD_MANUAL_TRANSMISSION", "RECORD_MANUAL_FAILURE"]
    assert body["blocked_actions"] == {
        "RETRY": "Submission job can only be retried from FAILED_MANUAL or RESPONSE_REJECTED_MANUAL status",
        "RECORD_MANUAL_RESPONSE": "CRA response can only be recorded after transmission is recorded"
    }
    assert body["terminal_outcome"] == "IN_PROGRESS"
    assert body["terminal_outcome_detail"] is None
    assert body["can_queue"] is True
    assert body["can_retry"] is False
    assert body["can_record_manual_transmission"] is True
    assert body["can_record_manual_response"] is False
    assert body["can_record_manual_failure"] is True
    assert body["queued_at"] is not None
    assert body["transmission_reference"] is None
    assert body["failure_code"] is None
    assert body["response_status"] is None

    queued_again = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/queue",
        headers=_owner_headers(company_id),
    )
    assert queued_again.status_code == 200, queued_again.text
    assert queued_again.json() == body

    db = SessionLocal()
    try:
        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_queued")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payload_json["submission_job_id"] == submission_job_id
        assert audit_events[0].payload_json["queued_at"] == body["queued_at"]
        assert audit_events[0].payload_json["validation_validator_id"] == body["validation_validator_id"]
        assert audit_events[0].payload_json["validation_validator_version"] == body["validation_validator_version"]
        assert audit_events[0].payload_json["validation_mode"] == body["validation_mode"]
        assert audit_events[0].payload_json["validation_status"] == body["validation_status"]
        assert audit_events[0].payload_json["validated_at"] == body["validated_at"]
        assert audit_events[0].payload_json["validated_by_user_id"] == body["validated_by_user_id"]

        outbox_rows = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.event_type == "PAYROLL_T4_SUBMISSION_JOB_QUEUED")
            .all()
        )
        assert len(outbox_rows) == 1
        assert outbox_rows[0].payload["submission_job_id"] == submission_job_id
        assert outbox_rows[0].payload["queued_at"] == body["queued_at"]
        assert outbox_rows[0].payload["validation_validator_id"] == body["validation_validator_id"]
        assert outbox_rows[0].payload["validation_validator_version"] == body["validation_validator_version"]
        assert outbox_rows[0].payload["validation_mode"] == body["validation_mode"]
        assert outbox_rows[0].payload["validation_status"] == body["validation_status"]
        assert outbox_rows[0].payload["validated_at"] == body["validated_at"]
        assert outbox_rows[0].payload["validated_by_user_id"] == body["validated_by_user_id"]
        assert outbox_rows[0].processed is False

        processed = process_outbox_batch(
            db=db,
            now=datetime.now(timezone.utc),
            batch_size=10,
            max_retries=10,
        )
        assert processed.processed == 1
        assert processed.failed == 0
        db.refresh(outbox_rows[0])
        assert outbox_rows[0].processed is True
        assert outbox_rows[0].processed_at is not None
    finally:
        db.close()

    detail_after_processing = client.get(
        f"/payroll/t4s/submission-jobs/{submission_job_id}",
        headers=_owner_headers(company_id),
    )
    assert detail_after_processing.status_code == 200, detail_after_processing.text
    detail_body = detail_after_processing.json()
    assert detail_body["id"] == body["id"]
    assert detail_body["status"] == body["status"]
    assert detail_body["queued_at"] == body["queued_at"]
    assert detail_body["transmission_reference"] == body["transmission_reference"]
    assert detail_body["validation_validator_id"] == body["validation_validator_id"]
    assert detail_body["validation_validator_version"] == body["validation_validator_version"]
    assert detail_body["validation_mode"] == body["validation_mode"]
    assert detail_body["validation_status"] == body["validation_status"]
    assert detail_body["validated_at"] == body["validated_at"]
    assert detail_body["validated_by_user_id"] == body["validated_by_user_id"]


def test_t4_submission_job_queue_repairs_persisted_validation_snapshot_fields_on_first_queue():
    company_id = 681132
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        row.filing_artifact_sha256 = f" {created.json()['artifact_sha256']} "
        row.xml_package_sha256 = f" {created.json()['xml_package_sha256']} "
        row.validation_validator_id = f" {created.json()['validation_validator_id']} "
        row.validation_validator_version = f" {created.json()['validation_validator_version']} "
        row.validated_by_user_id = f" {created.json()['validated_by_user_id']} "
        row.validated_at = row.validated_at.replace(tzinfo=None)
        db.commit()
    finally:
        db.close()

    queued = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/queue",
        headers=_owner_headers(company_id),
    )
    assert queued.status_code == 200, queued.text
    body = queued.json()

    assert body["artifact_sha256"] == created.json()["artifact_sha256"]
    assert body["xml_package_sha256"] == created.json()["xml_package_sha256"]
    assert body["validation_validator_id"] == created.json()["validation_validator_id"]
    assert body["validation_validator_version"] == created.json()["validation_validator_version"]
    assert body["validation_mode"] == created.json()["validation_mode"]
    assert body["validation_status"] == created.json()["validation_status"]
    assert body["validated_at"] == created.json()["validated_at"]
    assert body["validated_by_user_id"] == created.json()["validated_by_user_id"]

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == submission_job_id)
            .one()
        )
        assert row.filing_artifact_sha256 == created.json()["artifact_sha256"]
        assert row.xml_package_sha256 == created.json()["xml_package_sha256"]
        assert row.validation_validator_id == created.json()["validation_validator_id"]
        assert row.validation_validator_version == created.json()["validation_validator_version"]
        assert row.validated_by_user_id == created.json()["validated_by_user_id"]
        assert row.validated_at.astimezone(timezone.utc).isoformat() == created.json()["validated_at"]

        outbox_row = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.event_type == "PAYROLL_T4_SUBMISSION_JOB_QUEUED")
            .one()
        )
        assert outbox_row.payload["artifact_sha256"] == created.json()["artifact_sha256"]
        assert outbox_row.payload["xml_package_sha256"] == created.json()["xml_package_sha256"]
        assert outbox_row.payload["validation_validator_id"] == created.json()["validation_validator_id"]
        assert outbox_row.payload["validation_validator_version"] == created.json()["validation_validator_version"]
        assert outbox_row.payload["validated_at"] == created.json()["validated_at"]
        assert outbox_row.payload["validated_by_user_id"] == created.json()["validated_by_user_id"]
    finally:
        db.close()


def test_t4_submission_job_queue_rejects_non_prepared_states():
    company_id = 681131
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    submission_job_id = created.json()["id"]

    recorded_failure = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/record-failure",
        headers=_owner_headers(company_id),
        json={"failure_code": "BLOCKED"},
    )
    assert recorded_failure.status_code == 200, recorded_failure.text

    queued_after_failure = client.post(
        f"/payroll/t4s/submission-jobs/{submission_job_id}/queue",
        headers=_owner_headers(company_id),
    )
    assert queued_after_failure.status_code == 409
    assert queued_after_failure.json()["detail"] == "Submission job can only be queued from PREPARED status"

def test_t4_submission_job_persists_validation_snapshot_after_filing_artifact_changes():
    company_id = 681119
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    created_body = created.json()

    db = SessionLocal()
    try:
        profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).one()
        profile.company_name = "Submission Snapshot Company"
        db.commit()
    finally:
        db.close()

    refreshed_artifact = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert refreshed_artifact.status_code == 200, refreshed_artifact.text

    detail = client.get(
        f"/payroll/t4s/submission-jobs/{created_body['id']}",
        headers=_owner_headers(company_id),
    )
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()

    assert detail_body["validation_validator_id"] == created_body["validation_validator_id"]
    assert detail_body["validation_validator_version"] == created_body["validation_validator_version"]
    assert detail_body["validation_mode"] == created_body["validation_mode"]
    assert detail_body["validation_status"] == created_body["validation_status"]
    assert detail_body["validated_at"] == created_body["validated_at"]
    assert detail_body["validated_by_user_id"] == created_body["validated_by_user_id"]


def test_t4_submission_job_create_idempotent_retry_repairs_persisted_filing_artifact_id():
    company_id = 681121
    _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    created_body = created.json()

    db = SessionLocal()
    try:
        db.add(
            PayrollT4FilingArtifact(
                filing_artifact_id="artifact-foreign-api-681121",
                company_id=999121,
                tax_year=2025,
                filing_status="FILING_ARTIFACT_READY",
                prepared_payload_json={"schema_id": "frontier_payroll_cra_t4_filing_package", "schema_version": "1.0"},
                artifact_storage_key="db://artifact-foreign-api-681121.json",
                artifact_file_name="artifact-foreign-api-681121.json",
                artifact_content_type="application/json",
                artifact_blob=b"{}",
                artifact_byte_size=2,
                artifact_sha256="artifact-hash-foreign-api-681121",
            )
        )
        db.flush()

        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == created_body["id"])
            .one()
        )
        row.filing_artifact_id = "artifact-foreign-api-681121"
        db.commit()
    finally:
        db.close()

    created_again = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created_again.status_code == 200, created_again.text
    repaired_body = created_again.json()

    assert repaired_body["id"] == created_body["id"]
    assert repaired_body["filing_artifact_id"] == created_body["filing_artifact_id"]

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollT4SubmissionJob)
            .filter(PayrollT4SubmissionJob.company_id == company_id)
            .filter(PayrollT4SubmissionJob.id == created_body["id"])
            .one()
        )
        assert row.filing_artifact_id == created_body["filing_artifact_id"]

        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_submission_job_created")
            .all()
        )
        assert len(audit_events) == 1
    finally:
        db.close()


def test_t4_submission_job_persists_artifact_hash_snapshot_after_filing_artifact_changes():
    company_id = 681120
    prepared = _prepare_ready_t4_submission_package(company_id=company_id)

    created = client.post("/payroll/t4s/submission-jobs?tax_year=2026", headers=_owner_headers(company_id))
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body["artifact_sha256"] == prepared["artifact"]["filing_artifact"]["sha256"]

    db = SessionLocal()
    try:
        profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).one()
        profile.company_name = "Artifact Snapshot Company"
        db.commit()
    finally:
        db.close()

    refreshed_artifact = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert refreshed_artifact.status_code == 200, refreshed_artifact.text
    refreshed_body = refreshed_artifact.json()
    assert refreshed_body["filing_artifact"]["sha256"] != created_body["artifact_sha256"]

    detail = client.get(
        f"/payroll/t4s/submission-jobs/{created_body['id']}",
        headers=_owner_headers(company_id),
    )
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()

    assert detail_body["artifact_sha256"] == created_body["artifact_sha256"]


def test_payroll_t4_filing_package_is_deterministic_for_same_tax_year_input():
    company_id = 68111
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-filing-deterministic-1",
        pay_period_id="pp-t4-filing-deterministic-1",
        posted_at=datetime(2026, 4, 18, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Deterministic Worker A",
                "gross_pay_cents": 94_000,
                "deductions": {"CPP": 5_640, "EI": 1_880, "TAX": 15_000},
            },
            {
                "name": "Deterministic Worker B",
                "gross_pay_cents": 51_000,
                "deductions": {"CPP": 3_060, "EI": 1_020, "TAX": 8_200, "UNION_DUES": 900},
            },
        ],
    )

    db = SessionLocal()
    try:
        ordered_names = ["Deterministic Worker A", "Deterministic Worker B"]
        for index, employee_name in enumerate(ordered_names, start=1):
            employee = (
                db.query(Employee)
                .filter(Employee.company_id == company_id)
                .filter(Employee.id == employee_ids[employee_name])
                .one()
            )
            employee.legal_name = employee_name
            employee.sin = f"99900000{index}"
            employee.address_line_1 = f"{index} Stable St"
            employee.city = "Calgary"
            employee.province = "AB"
            employee.postal_code = f"T2P1A{index}"
            employee.country = "CA"
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    first_missing = client.get("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert first_missing.status_code == 404
    assert first_missing.json()["detail"] == "Payroll T4 filing artifact not found"

    first = client.post("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert first.status_code == 200, first.text
    second = client.get("/payroll/t4s/filing-artifact?tax_year=2026", headers=_owner_headers(company_id))
    assert second.status_code == 200, second.text

    first_body = first.json()
    second_body = second.json()
    assert first_body["filing_artifact"]["sha256"] == second_body["filing_artifact"]["sha256"]
    assert first_body["filing_package"] == second_body["filing_package"]
    assert [row["employee_display_name"] for row in first_body["filing_package"]["t4_rows"]] == [
        "Deterministic Worker A",
        "Deterministic Worker B",
    ]

    xml_first = client.post("/payroll/t4s/xml-package?tax_year=2026", headers=_owner_headers(company_id))
    assert xml_first.status_code == 200, xml_first.text
    xml_second = client.get("/payroll/t4s/xml-package?tax_year=2026", headers=_owner_headers(company_id))
    assert xml_second.status_code == 200, xml_second.text
    assert xml_first.json()["xml_package"]["sha256"] == xml_second.json()["xml_package"]["sha256"]
    assert xml_first.json()["xml"] == xml_second.json()["xml"]

    db = SessionLocal()
    try:
        artifact_row = (
            db.query(PayrollT4FilingArtifact)
            .filter(PayrollT4FilingArtifact.company_id == company_id)
            .filter(PayrollT4FilingArtifact.tax_year == 2026)
            .one()
        )
        assert artifact_row.artifact_sha256 == first_body["filing_artifact"]["sha256"]
        assert artifact_row.prepared_payload_json == first_body["filing_package"]
        assert artifact_row.xml_package_sha256 == xml_first.json()["xml_package"]["sha256"]
    finally:
        db.close()


def test_payroll_t4_export_preparation_reports_missing_cra_registration_identifiers():
    company_id = 68107
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-cra-blocked-1",
        pay_period_id="pp-t4-cra-blocked-1",
        posted_at=datetime(2026, 12, 15, tzinfo=timezone.utc),
        employees=[
            {
                "name": "CRA Ready Worker",
                "gross_pay_cents": 88_000,
                "deductions": {"CPP": 5_280, "EI": 1_760, "TAX": 14_200},
            },
        ],
    )

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.company_id == company_id)
            .filter(Employee.id == employee_ids["CRA Ready Worker"])
            .one()
        )
        employee.legal_name = "CRA Ready Worker"
        employee.sin = "987654321"
        employee.address_line_1 = "500 4 Ave SW"
        employee.city = "Calgary"
        employee.province = "AB"
        employee.postal_code = "T2P2V6"
        employee.country = "CA"

        profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).one()
        profile.cra_business_number = None
        profile.cra_payroll_program_account_number = None
        profile.payroll_registration_country = None
        db.commit()
    finally:
        db.close()

    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text

    export = client.get("/payroll/t4s/export-preparation?tax_year=2026", headers=_owner_headers(company_id))
    assert export.status_code == 200, export.text
    body = export.json()

    assert body["export_ready"] is False
    assert body["export_status"] == "EXPORT_PREPARATION_BLOCKED"
    assert any(issue["code"] == "cra_business_number_missing" for issue in body["blocking_issues"])
    assert any(issue["code"] == "cra_payroll_program_account_number_missing" for issue in body["blocking_issues"])
    assert any(issue["code"] == "payroll_registration_country_missing" for issue in body["blocking_issues"])


def test_employee_self_service_t4s_return_generated_records_and_stay_self_scoped():
    company_id = 68105
    _save_company_profile(company_id)
    employee_ids = _seed_posted_run(
        company_id=company_id,
        payroll_run_id="pr-t4-self-1",
        pay_period_id="pp-t4-self-1",
        posted_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        employees=[
            {
                "name": "Self T4 Worker",
                "gross_pay_cents": 91_000,
                "deductions": {"CPP": 5_460, "EI": 1_820, "TAX": 14_500},
            },
            {
                "name": "Other T4 Worker",
                "gross_pay_cents": 50_000,
                "deductions": {"CPP": 3_000, "EI": 1_000, "TAX": 7_500},
            },
        ],
    )
    generated = client.post("/payroll/t4s/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert generated.status_code == 200, generated.text
    slip_generated = client.post("/payroll/t4s/slips/generate", headers=_owner_headers(company_id), json={"tax_year": 2026})
    assert slip_generated.status_code == 200, slip_generated.text

    self_employee_id = employee_ids["Self T4 Worker"]
    other_employee_id = employee_ids["Other T4 Worker"]
    _create_account(
        company_id=company_id,
        username="self-t4-worker",
        email="self-t4-worker@example.com",
        password="SelfT4WorkerPass#1",
        role="EMPLOYEE_SELF_SERVICE",
        linked_employee_id=self_employee_id,
    )
    headers = _login_headers("self-t4-worker", "SelfT4WorkerPass#1", company_id)
    _set_pin(headers, "1234")
    headers["X-Employee-Pin"] = "1234"

    own = client.get(f"/employee-self-service/employees/{self_employee_id}/t4s", headers=headers)
    assert own.status_code == 200, own.text
    assert len(own.json()["rows"]) == 1
    assert own.json()["rows"][0]["employment_income_cents"] == 91_000
    assert own.json()["rows"][0]["status"] == "AVAILABLE"
    assert own.json()["rows"][0]["delivery_status"] == "PENDING_MANUAL"
    assert own.json()["rows"][0]["employee_download_count"] == 0
    assert own.json()["rows"][0]["employee_acknowledged_at"] is None
    assert own.json()["rows"][0]["slip_url"] == (
        f"/employee-self-service/employees/{self_employee_id}/t4s/{own.json()['rows'][0]['t4_id']}/download"
    )

    download = client.get(own.json()["rows"][0]["slip_url"], headers=headers)
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.content.startswith(b"%PDF-1.4")

    acknowledged = client.post(
        f"/employee-self-service/employees/{self_employee_id}/t4s/{own.json()['rows'][0]['t4_id']}/acknowledge",
        headers=headers,
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["employee_download_count"] == 1
    assert acknowledged.json()["employee_first_downloaded_at"] is not None
    assert acknowledged.json()["employee_last_downloaded_at"] is not None
    assert acknowledged.json()["employee_acknowledged_at"] is not None

    acknowledged_again = client.post(
        f"/employee-self-service/employees/{self_employee_id}/t4s/{own.json()['rows'][0]['t4_id']}/acknowledge",
        headers=headers,
    )
    assert acknowledged_again.status_code == 200, acknowledged_again.text
    assert acknowledged_again.json()["employee_acknowledged_at"] is not None
    assert acknowledged_again.json()["employee_download_count"] == acknowledged.json()["employee_download_count"]

    admin_view = client.get(f"/payroll/t4s?tax_year=2026&employee_id={self_employee_id}", headers=_owner_headers(company_id))
    assert admin_view.status_code == 200, admin_view.text
    assert admin_view.json()["rows"][0]["employee_download_count"] == 1
    assert admin_view.json()["rows"][0]["employee_has_downloaded"] is True
    assert admin_view.json()["rows"][0]["employee_last_downloaded_at"] is not None
    assert admin_view.json()["rows"][0]["employee_last_downloaded_by_user_id"] is not None
    assert admin_view.json()["rows"][0]["employee_acknowledged_at"] is not None
    assert admin_view.json()["rows"][0]["employee_acknowledged_by_user_id"] is not None
    assert admin_view.json()["rows"][0]["employee_has_acknowledged"] is True

    other = client.get(f"/employee-self-service/employees/{other_employee_id}/t4s", headers=headers)
    assert other.status_code == 403
    assert other.json()["detail"]["code"] == "self_employee_access_required"

    other_download = client.get(
        f"/employee-self-service/employees/{other_employee_id}/t4s/{own.json()['rows'][0]['t4_id']}/download",
        headers=headers,
    )
    assert other_download.status_code == 403
    assert other_download.json()["detail"]["code"] == "self_employee_access_required"

    other_ack = client.post(
        f"/employee-self-service/employees/{other_employee_id}/t4s/{own.json()['rows'][0]['t4_id']}/acknowledge",
        headers=headers,
    )
    assert other_ack.status_code == 403
    assert other_ack.json()["detail"]["code"] == "self_employee_access_required"

    db = SessionLocal()
    try:
        audit_events = (
            db.query(PayrollRunAuditEvent)
            .filter(PayrollRunAuditEvent.company_id == company_id)
            .filter(PayrollRunAuditEvent.event_type == "payroll_t4_acknowledged_by_employee")
            .all()
        )
        assert len(audit_events) == 1
        assert audit_events[0].payload_json["employee_id"] == self_employee_id
        assert audit_events[0].payload_json["t4_id"] == own.json()["rows"][0]["t4_id"]
        assert audit_events[0].actor_user_id is not None
    finally:
        db.close()

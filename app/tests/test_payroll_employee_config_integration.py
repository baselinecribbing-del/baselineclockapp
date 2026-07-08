from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.employee_payroll_enrollment import EmployeePayrollEnrollment
from app.models.employee_vacation_assignment import EmployeeVacationAssignment
from app.models.job import Job
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.scope import Scope
from app.models.time_entry import TimeEntry
from app.models.vacation_policy import VacationPolicy


client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "payroll-config-exec", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _seed_execution_case(*, company_id: int, suffix: str, pay_period_end_date: date) -> tuple[str, int]:
    pay_period_id = f"pp-config-{suffix}"
    work_day = pay_period_end_date - timedelta(days=5)
    started_at = datetime.combine(work_day, datetime.min.time()).replace(tzinfo=timezone.utc) + timedelta(hours=8)
    ended_at = started_at + timedelta(hours=4)

    db = SessionLocal()
    try:
        db.add(
            PayPeriod(
                pay_period_id=pay_period_id,
                company_id=company_id,
                start_date=pay_period_end_date - timedelta(days=13),
                end_date=pay_period_end_date,
                status="OPEN",
            )
        )
        job = Job(company_id=company_id, name=f"Payroll Config Job {suffix}", is_active=True)
        db.add(job)
        db.flush()
        scope = Scope(company_id=company_id, job_id=job.id, name=f"Payroll Config Scope {suffix}", is_active=True)
        db.add(scope)
        db.flush()
        employee = Employee(
            company_id=company_id,
            name=f"Payroll Config Employee {suffix}",
            legal_name=f"Payroll Config Employee {suffix}",
            hire_date=date(2026, 1, 1),
            requires_payroll=True,
            hourly_rate_cents=3000,
            payment_method="DIRECT_DEPOSIT",
            province_of_employment="AB",
            federal_claim_amount=150,
        )
        db.add(employee)
        db.flush()
        db.add(
            TimeEntry(
                time_entry_id=f"te-config-{suffix}",
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
        return pay_period_id, int(employee.id)
    finally:
        db.close()


def _seed_vacation_assignment(
    *,
    company_id: int,
    employee_id: int,
    name: str,
    payout_method: str,
    accrual_rate_percent: str | None = None,
    payout_rate_percent: str | None = None,
    effective_start_date: date,
    effective_end_date: date | None = None,
) -> None:
    db = SessionLocal()
    try:
        policy = VacationPolicy(
            company_id=company_id,
            name=name,
            payout_method=payout_method,
            accrual_rate_percent=accrual_rate_percent,
            payout_rate_percent=payout_rate_percent,
            is_active=True,
        )
        db.add(policy)
        db.flush()
        db.add(
            EmployeeVacationAssignment(
                company_id=company_id,
                employee_id=employee_id,
                vacation_policy_id=str(policy.vacation_policy_id),
                effective_start_date=effective_start_date,
                effective_end_date=effective_end_date,
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_enrollment(
    *,
    company_id: int,
    employee_id: int,
    code: str,
    category: str,
    employee_amount_cents: int,
    employer_amount_cents: int,
    effective_start_date: date,
    effective_end_date: date | None = None,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            EmployeePayrollEnrollment(
                company_id=company_id,
                employee_id=employee_id,
                code=code,
                name=code,
                category=category,
                employee_amount_cents=employee_amount_cents,
                employer_amount_cents=employer_amount_cents,
                frequency="per_pay_period",
                effective_start_date=effective_start_date,
                effective_end_date=effective_end_date,
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()


def test_payroll_execution_uses_effective_employee_configs_and_outputs_them():
    company_id = 67001
    pay_period_id, employee_id = _seed_execution_case(
        company_id=company_id,
        suffix="effective",
        pay_period_end_date=date(2026, 6, 15),
    )
    _seed_vacation_assignment(
        company_id=company_id,
        employee_id=employee_id,
        name="Old Vacation",
        payout_method="each_pay_period",
        payout_rate_percent="4.00",
        effective_start_date=date(2026, 1, 1),
        effective_end_date=date(2026, 5, 31),
    )
    _seed_vacation_assignment(
        company_id=company_id,
        employee_id=employee_id,
        name="Current Vacation",
        payout_method="each_pay_period",
        payout_rate_percent="6.00",
        effective_start_date=date(2026, 6, 1),
    )
    _seed_enrollment(
        company_id=company_id,
        employee_id=employee_id,
        code="HEALTH",
        category="benefit",
        employee_amount_cents=500,
        employer_amount_cents=1000,
        effective_start_date=date(2026, 1, 1),
        effective_end_date=date(2026, 5, 31),
    )
    _seed_enrollment(
        company_id=company_id,
        employee_id=employee_id,
        code="HEALTH",
        category="benefit",
        employee_amount_cents=1000,
        employer_amount_cents=2500,
        effective_start_date=date(2026, 6, 1),
    )

    resp = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    payroll_run_id = body["payroll_run_id"]

    overview_row = body["processing_overview"]["pay_employees"]["rows"][0]
    assert overview_row["gross_pay_cents"] == 12720
    assert overview_row["deductions_cents"] == 2017
    assert overview_row["net_pay_cents"] == 10703

    deductions = client.get(f"/payroll/runs/{payroll_run_id}/deductions", headers=_auth_headers(company_id))
    assert deductions.status_code == 200, deductions.text
    rows = deductions.json()["rows"]
    by_type = {row["deduction_type"]: row for row in rows}
    assert by_type["CPP"]["amount_cents"] == 763
    assert by_type["EI"]["amount_cents"] == 254
    assert by_type["HEALTH_EMPLOYEE"]["amount_cents"] == 1000
    assert by_type["HEALTH_EMPLOYEE"]["paystub_id"] is not None
    assert by_type["HEALTH_EMPLOYER"]["amount_cents"] == 2500
    assert by_type["HEALTH_EMPLOYER"]["paystub_id"] is None

    paystubs = client.get(f"/payroll/runs/{payroll_run_id}/paystubs", headers=_auth_headers(company_id))
    assert paystubs.status_code == 200, paystubs.text
    paystub_id = paystubs.json()["rows"][0]["paystub_id"]
    assert paystubs.json()["rows"][0]["gross_pay_cents"] == 12720
    assert paystubs.json()["rows"][0]["total_deductions_cents"] == 2017
    assert paystubs.json()["rows"][0]["net_pay_cents"] == 10703

    paystub_detail = client.get(
        f"/payroll/runs/{payroll_run_id}/paystubs/{paystub_id}",
        headers=_auth_headers(company_id),
    )
    assert paystub_detail.status_code == 200, paystub_detail.text
    assert {row["deduction_type"] for row in paystub_detail.json()["deductions"]} == {
        "CPP",
        "EI",
        "HEALTH_EMPLOYEE",
    }

    db = SessionLocal()
    try:
        items = (
            db.query(PayrollItem)
            .filter(PayrollItem.company_id == company_id)
            .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
            .order_by(PayrollItem.id.asc())
            .all()
        )
        vacation_item = next(item for item in items if item.meta and item.meta.get("source") == "VACATION_POLICY_PAYOUT")
        assert int(vacation_item.gross_pay_cents) == 720
        assert vacation_item.meta["rate_percent"] == "6.0000"
        assert vacation_item.meta["as_of_date"] == "2026-06-15"
    finally:
        db.close()


def test_employer_side_contributions_do_not_reduce_paystub_net_pay():
    company_id = 67002
    pay_period_id, employee_id = _seed_execution_case(
        company_id=company_id,
        suffix="employer",
        pay_period_end_date=date(2026, 7, 15),
    )
    _seed_enrollment(
        company_id=company_id,
        employee_id=employee_id,
        code="RRSP",
        category="benefit",
        employee_amount_cents=0,
        employer_amount_cents=3000,
        effective_start_date=date(2026, 1, 1),
    )

    resp = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert resp.status_code == 200, resp.text
    payroll_run_id = resp.json()["payroll_run_id"]

    paystubs = client.get(f"/payroll/runs/{payroll_run_id}/paystubs", headers=_auth_headers(company_id))
    assert paystubs.status_code == 200, paystubs.text
    paystub = paystubs.json()["rows"][0]
    assert paystub["gross_pay_cents"] == 12000
    assert paystub["total_deductions_cents"] == 960
    assert paystub["net_pay_cents"] == 11040

    deductions = client.get(f"/payroll/runs/{payroll_run_id}/deductions", headers=_auth_headers(company_id))
    assert deductions.status_code == 200, deductions.text
    by_type = {row["deduction_type"]: row for row in deductions.json()["rows"]}
    assert by_type["RRSP_EMPLOYER"]["amount_cents"] == 3000
    assert by_type["RRSP_EMPLOYER"]["paystub_id"] is None


def test_accrued_vacation_policy_is_deferred_and_not_paid_out_in_run():
    company_id = 67003
    pay_period_id, employee_id = _seed_execution_case(
        company_id=company_id,
        suffix="accrued",
        pay_period_end_date=date(2026, 8, 15),
    )
    _seed_vacation_assignment(
        company_id=company_id,
        employee_id=employee_id,
        name="Accrued Vacation",
        payout_method="accrued",
        accrual_rate_percent="4.00",
        effective_start_date=date(2026, 1, 1),
    )

    resp = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert resp.status_code == 200, resp.text
    payroll_run_id = resp.json()["payroll_run_id"]

    paystubs = client.get(f"/payroll/runs/{payroll_run_id}/paystubs", headers=_auth_headers(company_id))
    assert paystubs.status_code == 200, paystubs.text
    assert paystubs.json()["rows"][0]["gross_pay_cents"] == 12000

    db = SessionLocal()
    try:
        items = (
            db.query(PayrollItem)
            .filter(PayrollItem.company_id == company_id)
            .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
            .all()
        )
        assert all(not (item.meta and item.meta.get("source") == "VACATION_POLICY_PAYOUT") for item in items)
    finally:
        db.close()


def test_company_isolation_applies_to_employee_payroll_config_lookup():
    owner_company_id = 67004
    other_company_id = 67005
    pay_period_id, employee_id = _seed_execution_case(
        company_id=owner_company_id,
        suffix="scope-owner",
        pay_period_end_date=date(2026, 9, 15),
    )
    other_pay_period_id, other_employee_id = _seed_execution_case(
        company_id=other_company_id,
        suffix="scope-other",
        pay_period_end_date=date(2026, 9, 15),
    )
    _seed_enrollment(
        company_id=owner_company_id,
        employee_id=employee_id,
        code="UNION",
        category="deduction",
        employee_amount_cents=900,
        employer_amount_cents=0,
        effective_start_date=date(2026, 1, 1),
    )
    _seed_enrollment(
        company_id=other_company_id,
        employee_id=other_employee_id,
        code="UNION",
        category="deduction",
        employee_amount_cents=1500,
        employer_amount_cents=0,
        effective_start_date=date(2026, 1, 1),
    )

    owner_run = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(owner_company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert owner_run.status_code == 200, owner_run.text
    owner_deductions = client.get(
        f"/payroll/runs/{owner_run.json()['payroll_run_id']}/deductions",
        headers=_auth_headers(owner_company_id),
    )
    assert owner_deductions.status_code == 200, owner_deductions.text
    owner_union = next(row for row in owner_deductions.json()["rows"] if row["deduction_type"] == "UNION_EMPLOYEE")
    assert owner_union["amount_cents"] == 900

    other_run = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(other_company_id),
        json={"pay_period_id": other_pay_period_id},
    )
    assert other_run.status_code == 200, other_run.text
    other_deductions = client.get(
        f"/payroll/runs/{other_run.json()['payroll_run_id']}/deductions",
        headers=_auth_headers(other_company_id),
    )
    assert other_deductions.status_code == 200, other_deductions.text
    other_union = next(row for row in other_deductions.json()["rows"] if row["deduction_type"] == "UNION_EMPLOYEE")
    assert other_union["amount_cents"] == 1500


def test_run_uses_current_history_slice_for_lookup():
    company_id = 67006
    pay_period_id, employee_id = _seed_execution_case(
        company_id=company_id,
        suffix="history",
        pay_period_end_date=date(2026, 10, 15),
    )
    _seed_enrollment(
        company_id=company_id,
        employee_id=employee_id,
        code="DENTAL",
        category="benefit",
        employee_amount_cents=700,
        employer_amount_cents=1700,
        effective_start_date=date(2026, 1, 1),
        effective_end_date=date(2026, 8, 31),
    )
    _seed_enrollment(
        company_id=company_id,
        employee_id=employee_id,
        code="DENTAL",
        category="benefit",
        employee_amount_cents=1100,
        employer_amount_cents=2100,
        effective_start_date=date(2026, 9, 1),
    )

    resp = client.post(
        "/payroll/processing/execute",
        headers=_auth_headers(company_id),
        json={"pay_period_id": pay_period_id},
    )
    assert resp.status_code == 200, resp.text
    deductions = client.get(
        f"/payroll/runs/{resp.json()['payroll_run_id']}/deductions",
        headers=_auth_headers(company_id),
    )
    assert deductions.status_code == 200, deductions.text
    by_type = {row["deduction_type"]: row for row in deductions.json()["rows"]}
    assert by_type["DENTAL_EMPLOYEE"]["amount_cents"] == 1100
    assert by_type["DENTAL_EMPLOYER"]["amount_cents"] == 2100

from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee


client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "payroll-config-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _seed_employee(company_id: int, name: str) -> int:
    db = SessionLocal()
    try:
        row = Employee(
            company_id=company_id,
            name=name,
            legal_name=name,
            hire_date=date(2026, 1, 1),
            hourly_rate_cents=3200,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def test_employee_vacation_assignment_read_write():
    company_id = 66001
    employee_id = _seed_employee(company_id, "Vacation Employee")

    put_resp = client.put(
        f"/payroll/employees/{employee_id}/vacation",
        headers=_auth_headers(company_id),
        json={
            "policy": {
                "name": "Standard 6 Percent",
                "payout_rate_percent": "6.00",
                "payout_method": "each_pay_period",
            },
            "effective_start_date": "2026-01-01",
        },
    )
    assert put_resp.status_code == 200, put_resp.text
    body = put_resp.json()
    assert body["employee_id"] == employee_id
    assert body["policy"]["name"] == "Standard 6 Percent"
    assert body["policy"]["payout_rate_percent"] == "6.00"
    assert body["policy"]["payout_method"] == "each_pay_period"

    get_resp = client.get(
        f"/payroll/employees/{employee_id}/vacation",
        headers=_auth_headers(company_id),
        params={"as_of_date": "2026-03-11"},
    )
    assert get_resp.status_code == 200, get_resp.text
    config = get_resp.json()
    assert config["employee_id"] == employee_id
    assert config["current_assignment"]["assignment_id"] == body["assignment_id"]
    assert len(config["assignments"]) == 1


def test_employee_benefit_enrollment_create_read_and_update():
    company_id = 66002
    employee_id = _seed_employee(company_id, "Benefits Employee")

    created = client.post(
        f"/payroll/employees/{employee_id}/benefits-deductions",
        headers=_auth_headers(company_id),
        json={
            "code": "HEALTH",
            "name": "Extended Health",
            "category": "benefit",
            "employee_amount_cents": 12500,
            "employer_amount_cents": 25000,
            "frequency": "per_pay_period",
            "effective_start_date": "2026-01-01",
            "notes": "Starts after probation",
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["code"] == "HEALTH"
    assert row["category"] == "benefit"
    assert row["employee_amount_cents"] == 12500

    listing = client.get(
        f"/payroll/employees/{employee_id}/benefits-deductions",
        headers=_auth_headers(company_id),
        params={"as_of_date": "2026-03-11"},
    )
    assert listing.status_code == 200, listing.text
    listed = listing.json()
    assert len(listed["current_enrollments"]) == 1
    assert listed["current_enrollments"][0]["enrollment_id"] == row["enrollment_id"]

    updated = client.patch(
        f"/payroll/employees/{employee_id}/benefits-deductions/{row['enrollment_id']}",
        headers=_auth_headers(company_id),
        json={
            "employee_amount_cents": 13000,
            "employer_amount_cents": 25500,
            "notes": "Updated after rate change",
        },
    )
    assert updated.status_code == 200, updated.text
    updated_row = updated.json()
    assert updated_row["employee_amount_cents"] == 13000
    assert updated_row["employer_amount_cents"] == 25500
    assert updated_row["notes"] == "Updated after rate change"


def test_effective_dated_history_is_preserved_for_vacation_and_benefits():
    company_id = 66003
    employee_id = _seed_employee(company_id, "History Employee")

    first_vacation = client.put(
        f"/payroll/employees/{employee_id}/vacation",
        headers=_auth_headers(company_id),
        json={
            "policy": {
                "name": "Standard Accrued",
                "accrual_rate_percent": "4.00",
                "payout_method": "accrued",
            },
            "effective_start_date": "2026-01-01",
        },
    )
    assert first_vacation.status_code == 200, first_vacation.text

    second_vacation = client.put(
        f"/payroll/employees/{employee_id}/vacation",
        headers=_auth_headers(company_id),
        json={
            "policy": {
                "name": "Senior Accrued",
                "accrual_rate_percent": "6.00",
                "payout_method": "accrued",
            },
            "effective_start_date": "2026-04-01",
        },
    )
    assert second_vacation.status_code == 200, second_vacation.text

    vacation_config = client.get(
        f"/payroll/employees/{employee_id}/vacation",
        headers=_auth_headers(company_id),
        params={"as_of_date": "2026-04-15"},
    )
    assert vacation_config.status_code == 200, vacation_config.text
    vacation_rows = vacation_config.json()["assignments"]
    assert len(vacation_rows) == 2
    older_assignment = next(row for row in vacation_rows if row["policy"]["name"] == "Standard Accrued")
    current_assignment = vacation_config.json()["current_assignment"]
    assert older_assignment["effective_end_date"] == "2026-03-31"
    assert current_assignment["policy"]["name"] == "Senior Accrued"

    first_benefit = client.post(
        f"/payroll/employees/{employee_id}/benefits-deductions",
        headers=_auth_headers(company_id),
        json={
            "code": "RRSP",
            "name": "RRSP Match",
            "category": "benefit",
            "employee_amount_cents": 5000,
            "employer_amount_cents": 5000,
            "frequency": "per_pay_period",
            "effective_start_date": "2026-01-01",
        },
    )
    assert first_benefit.status_code == 200, first_benefit.text

    second_benefit = client.post(
        f"/payroll/employees/{employee_id}/benefits-deductions",
        headers=_auth_headers(company_id),
        json={
            "code": "RRSP",
            "name": "RRSP Match",
            "category": "benefit",
            "employee_amount_cents": 7500,
            "employer_amount_cents": 7500,
            "frequency": "per_pay_period",
            "effective_start_date": "2026-06-01",
        },
    )
    assert second_benefit.status_code == 200, second_benefit.text

    enrollment_config = client.get(
        f"/payroll/employees/{employee_id}/benefits-deductions",
        headers=_auth_headers(company_id),
        params={"as_of_date": "2026-06-15"},
    )
    assert enrollment_config.status_code == 200, enrollment_config.text
    enrollment_rows = enrollment_config.json()["enrollments"]
    assert len(enrollment_rows) == 2
    older_enrollment = next(row for row in enrollment_rows if row["employee_amount_cents"] == 5000)
    current_enrollment = next(row for row in enrollment_config.json()["current_enrollments"] if row["code"] == "RRSP")
    assert older_enrollment["effective_end_date"] == "2026-05-31"
    assert current_enrollment["employee_amount_cents"] == 7500


def test_company_isolation_is_enforced_for_employee_payroll_config():
    owner_company_id = 66004
    other_company_id = 66005
    employee_id = _seed_employee(owner_company_id, "Scoped Employee")

    own_create = client.post(
        f"/payroll/employees/{employee_id}/benefits-deductions",
        headers=_auth_headers(owner_company_id),
        json={
            "code": "UNION",
            "name": "Union Dues",
            "category": "deduction",
            "employee_amount_cents": 2500,
            "employer_amount_cents": 0,
            "frequency": "per_pay_period",
            "effective_start_date": "2026-01-01",
        },
    )
    assert own_create.status_code == 200, own_create.text
    enrollment_id = own_create.json()["enrollment_id"]

    other_vacation = client.get(
        f"/payroll/employees/{employee_id}/vacation",
        headers=_auth_headers(other_company_id),
    )
    assert other_vacation.status_code == 404, other_vacation.text

    other_create = client.post(
        f"/payroll/employees/{employee_id}/benefits-deductions",
        headers=_auth_headers(other_company_id),
        json={
            "code": "UNION",
            "name": "Union Dues",
            "category": "deduction",
            "employee_amount_cents": 2500,
            "employer_amount_cents": 0,
            "frequency": "per_pay_period",
            "effective_start_date": "2026-01-01",
        },
    )
    assert other_create.status_code == 404, other_create.text

    other_patch = client.patch(
        f"/payroll/employees/{employee_id}/benefits-deductions/{enrollment_id}",
        headers=_auth_headers(other_company_id),
        json={"notes": "intrusion"},
    )
    assert other_patch.status_code == 404, other_patch.text


def test_invalid_employee_returns_404_for_payroll_config_endpoints():
    company_id = 66006

    get_resp = client.get("/payroll/employees/999999/vacation", headers=_auth_headers(company_id))
    assert get_resp.status_code == 404, get_resp.text

    post_resp = client.post(
        "/payroll/employees/999999/benefits-deductions",
        headers=_auth_headers(company_id),
        json={
            "code": "HEALTH",
            "name": "Health",
            "category": "benefit",
            "employee_amount_cents": 1000,
            "employer_amount_cents": 1000,
            "frequency": "per_pay_period",
            "effective_start_date": "2026-01-01",
        },
    )
    assert post_resp.status_code == 404, post_resp.text


def test_overlapping_active_records_are_rejected():
    company_id = 66007
    employee_id = _seed_employee(company_id, "Overlap Employee")

    initial_vacation = client.put(
        f"/payroll/employees/{employee_id}/vacation",
        headers=_auth_headers(company_id),
        json={
            "policy": {
                "name": "Base Vacation",
                "payout_rate_percent": "4.00",
                "payout_method": "each_pay_period",
            },
            "effective_start_date": "2026-01-01",
            "effective_end_date": "2026-12-31",
        },
    )
    assert initial_vacation.status_code == 200, initial_vacation.text

    overlapping_vacation = client.put(
        f"/payroll/employees/{employee_id}/vacation",
        headers=_auth_headers(company_id),
        json={
            "policy": {
                "name": "Base Vacation",
                "payout_rate_percent": "4.00",
                "payout_method": "each_pay_period",
            },
            "effective_start_date": "2026-06-01",
            "effective_end_date": "2026-12-31",
        },
    )
    assert overlapping_vacation.status_code == 409, overlapping_vacation.text
    assert overlapping_vacation.json()["detail"] == "Vacation assignment effective dates overlap an existing assignment"

    initial_benefit = client.post(
        f"/payroll/employees/{employee_id}/benefits-deductions",
        headers=_auth_headers(company_id),
        json={
            "code": "DENTAL",
            "name": "Dental",
            "category": "benefit",
            "employee_amount_cents": 1000,
            "employer_amount_cents": 2000,
            "frequency": "per_pay_period",
            "effective_start_date": "2026-01-01",
            "effective_end_date": "2026-12-31",
        },
    )
    assert initial_benefit.status_code == 200, initial_benefit.text

    overlapping_benefit = client.post(
        f"/payroll/employees/{employee_id}/benefits-deductions",
        headers=_auth_headers(company_id),
        json={
            "code": "DENTAL",
            "name": "Dental",
            "category": "benefit",
            "employee_amount_cents": 1200,
            "employer_amount_cents": 2200,
            "frequency": "per_pay_period",
            "effective_start_date": "2026-03-01",
            "effective_end_date": "2026-09-30",
        },
    )
    assert overlapping_benefit.status_code == 409, overlapping_benefit.text
    assert overlapping_benefit.json()["detail"] == "Enrollment effective dates overlap an existing active record"

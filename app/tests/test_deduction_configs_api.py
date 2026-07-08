from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.deduction_type import DeductionType
from app.models.employee import Employee
from app.services.deduction_engine import compute_deduction_amounts


client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_employee(*, company_id: int, name: str) -> int:
    db = SessionLocal()
    try:
        row = Employee(company_id=company_id, name=name, hourly_rate_cents=3000)
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def _seed_deduction_type(*, company_id: int | None, code: str) -> str:
    db = SessionLocal()
    try:
        row = DeductionType(
            company_id=company_id,
            code=code,
            name=code,
            calculation_method="RATE_PERCENT",
            is_statutory=False,
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.deduction_type_id)
    finally:
        db.close()


def test_create_list_and_update_deduction_configs():
    company_id = 1
    headers = _auth_headers(company_id)
    employee_id = _seed_employee(company_id=company_id, name="Config API Emp")
    dtype_id = _seed_deduction_type(company_id=None, code="CFG_API_LIST")

    created = client.post(
        "/payroll/deduction-configs",
        headers=headers,
        json={
            "deduction_type_id": dtype_id,
            "employee_id": employee_id,
            "rate_percent": "12.5",
            "effective_from": date(2026, 1, 1).isoformat(),
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["deduction_type_id"] == dtype_id
    assert row["employee_id"] == employee_id
    assert row["rate_percent"] == "12.5000"
    assert row["amount_cents"] is None
    assert row["is_active"] is True

    listed = client.get("/payroll/deduction-configs", headers=headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["deduction_config_id"] == row["deduction_config_id"]

    updated = client.patch(
        f"/payroll/deduction-configs/{row['deduction_config_id']}",
        headers=headers,
        json={"amount_cents": 420, "annual_cap_cents": 1000},
    )
    assert updated.status_code == 200, updated.text
    updated_row = updated.json()
    assert updated_row["amount_cents"] == 420
    assert updated_row["rate_percent"] is None
    assert updated_row["annual_cap_cents"] == 1000


def test_employee_override_beats_company_default():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id, name="Override Emp")
    dtype_id = _seed_deduction_type(company_id=None, code="EMP_OVERRIDE")

    headers = _auth_headers(company_id)
    default_resp = client.post(
        "/payroll/deduction-configs",
        headers=headers,
        json={
            "deduction_type_id": dtype_id,
            "amount_cents": 150,
            "effective_from": date(2026, 1, 1).isoformat(),
        },
    )
    assert default_resp.status_code == 200, default_resp.text

    employee_resp = client.post(
        "/payroll/deduction-configs",
        headers=headers,
        json={
            "deduction_type_id": dtype_id,
            "employee_id": employee_id,
            "amount_cents": 275,
            "effective_from": date(2026, 1, 1).isoformat(),
        },
    )
    assert employee_resp.status_code == 200, employee_resp.text

    db = SessionLocal()
    try:
        rows = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
            as_of_date=date(2026, 1, 15),
        )
    finally:
        db.close()

    by_code = {str(r["deduction_type_code"]): int(r["amount_cents"]) for r in rows}
    assert by_code["EMP_OVERRIDE"] == 275


def test_company_scoped_type_config_beats_global_type_config():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id, name="Scope Override Emp")
    global_type_id = _seed_deduction_type(company_id=None, code="SCOPE_PRIORITY")
    company_type_id = _seed_deduction_type(company_id=company_id, code="SCOPE_PRIORITY")

    headers = _auth_headers(company_id)
    global_resp = client.post(
        "/payroll/deduction-configs",
        headers=headers,
        json={
            "deduction_type_id": global_type_id,
            "amount_cents": 110,
            "effective_from": date(2026, 1, 1).isoformat(),
        },
    )
    assert global_resp.status_code == 200, global_resp.text

    company_resp = client.post(
        "/payroll/deduction-configs",
        headers=headers,
        json={
            "deduction_type_id": company_type_id,
            "amount_cents": 330,
            "effective_from": date(2026, 1, 1).isoformat(),
        },
    )
    assert company_resp.status_code == 200, company_resp.text

    db = SessionLocal()
    try:
        rows = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
            as_of_date=date(2026, 1, 15),
        )
    finally:
        db.close()

    by_code = {str(r["deduction_type_code"]): int(r["amount_cents"]) for r in rows}
    assert by_code["SCOPE_PRIORITY"] == 330


def test_disabled_config_is_ignored():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id, name="Disabled Config Emp")
    disabled_type_id = _seed_deduction_type(company_id=None, code="DISABLED_CFG")
    active_type_id = _seed_deduction_type(company_id=None, code="ACTIVE_CFG")

    headers = _auth_headers(company_id)
    active_resp = client.post(
        "/payroll/deduction-configs",
        headers=headers,
        json={
            "deduction_type_id": active_type_id,
            "amount_cents": 125,
            "effective_from": date(2026, 1, 1).isoformat(),
        },
    )
    assert active_resp.status_code == 200, active_resp.text

    disabled_resp = client.post(
        "/payroll/deduction-configs",
        headers=headers,
        json={
            "deduction_type_id": disabled_type_id,
            "amount_cents": 999,
            "effective_from": date(2026, 1, 1).isoformat(),
        },
    )
    assert disabled_resp.status_code == 200, disabled_resp.text

    disable_call = client.post(
        f"/payroll/deduction-configs/{disabled_resp.json()['deduction_config_id']}/disable",
        headers=headers,
    )
    assert disable_call.status_code == 200, disable_call.text
    assert disable_call.json()["is_active"] is False

    db = SessionLocal()
    try:
        rows = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
            as_of_date=date(2026, 1, 15),
        )
    finally:
        db.close()

    by_code = {str(r["deduction_type_code"]): int(r["amount_cents"]) for r in rows}
    assert "DISABLED_CFG" not in by_code
    assert by_code["ACTIVE_CFG"] == 125


def test_effective_date_filtering_works():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id, name="Effective Date Emp")
    dtype_id = _seed_deduction_type(company_id=None, code="EFFECTIVE_WINDOW")

    headers = _auth_headers(company_id)
    today = date(2026, 2, 1)

    current_resp = client.post(
        "/payroll/deduction-configs",
        headers=headers,
        json={
            "deduction_type_id": dtype_id,
            "amount_cents": 210,
            "effective_from": (today - timedelta(days=10)).isoformat(),
            "effective_to": (today + timedelta(days=2)).isoformat(),
        },
    )
    assert current_resp.status_code == 200, current_resp.text

    future_resp = client.post(
        "/payroll/deduction-configs",
        headers=headers,
        json={
            "deduction_type_id": dtype_id,
            "amount_cents": 510,
            "effective_from": (today + timedelta(days=1)).isoformat(),
            "effective_to": None,
        },
    )
    assert future_resp.status_code == 200, future_resp.text

    db = SessionLocal()
    try:
        rows_today = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
            as_of_date=today,
        )
        rows_future = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
            as_of_date=today + timedelta(days=1),
        )
    finally:
        db.close()

    by_code_today = {str(r["deduction_type_code"]): int(r["amount_cents"]) for r in rows_today}
    by_code_future = {str(r["deduction_type_code"]): int(r["amount_cents"]) for r in rows_future}

    assert by_code_today["EFFECTIVE_WINDOW"] == 210
    assert by_code_future["EFFECTIVE_WINDOW"] == 510

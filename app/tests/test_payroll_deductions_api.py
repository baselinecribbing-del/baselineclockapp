from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.main import app
from app.models.deduction_config import DeductionConfig
from app.models.deduction_type import DeductionType
from app.models.employee import Employee
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_deduction import PayrollDeduction
from app.models.payroll_run import PayrollRun
from app.models.paystub import Paystub


client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_run_and_employee(*, company_id: int, pay_period_id: str, payroll_run_id: str) -> int:
    db = SessionLocal()
    try:
        emp = Employee(company_id=company_id, name=f"Deduction Emp {company_id}", hourly_rate_cents=3000)
        db.add(emp)
        db.flush()

        db.add(
            PayPeriod(
                pay_period_id=pay_period_id,
                company_id=company_id,
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 14),
                status="POSTED",
            )
        )
        db.flush()

        db.add(
            PayrollRun(
                payroll_run_id=payroll_run_id,
                company_id=company_id,
                pay_period_id=pay_period_id,
                status="FINALIZED",
                posted_at=None,
            )
        )
        db.commit()
        return emp.id
    finally:
        db.close()


def _seed_finalized_run_with_items(*, company_id: int, payroll_run_id: str, pay_period_id: str) -> tuple[int, int]:
    db = SessionLocal()
    try:
        e1 = Employee(company_id=company_id, name=f"GenDed Emp A {payroll_run_id}", hourly_rate_cents=3000)
        e2 = Employee(company_id=company_id, name=f"GenDed Emp B {payroll_run_id}", hourly_rate_cents=3200)
        db.add_all([e1, e2])
        db.flush()

        db.add(
            PayPeriod(
                pay_period_id=pay_period_id,
                company_id=company_id,
                start_date=date(2026, 12, 1),
                end_date=date(2026, 12, 14),
                status="POSTED",
            )
        )
        db.flush()

        db.add(
            PayrollRun(
                payroll_run_id=payroll_run_id,
                company_id=company_id,
                pay_period_id=pay_period_id,
                status="FINALIZED",
                posted_at=None,
            )
        )
        db.flush()

        db.add_all(
            [
                PayrollItem(
                    company_id=company_id,
                    payroll_run_id=payroll_run_id,
                    employee_id=e1.id,
                    hours=2,
                    rate_cents=3000,
                    gross_pay_cents=6000,
                    meta={"job_id": 1},
                ),
                PayrollItem(
                    company_id=company_id,
                    payroll_run_id=payroll_run_id,
                    employee_id=e2.id,
                    hours=3,
                    rate_cents=3200,
                    gross_pay_cents=9600,
                    meta={"job_id": 1},
                ),
            ]
        )
        db.commit()
        return e1.id, e2.id
    finally:
        db.close()


def _seed_custom_deduction_config(*, company_id: int, code: str, rate_percent: Decimal) -> None:
    db = SessionLocal()
    try:
        dtype = DeductionType(
            company_id=company_id,
            code=code,
            name=code,
            calculation_method="RATE_PERCENT",
            is_statutory=False,
            is_active=True,
        )
        db.add(dtype)
        db.flush()

        db.add(
            DeductionConfig(
                company_id=company_id,
                deduction_type_id=dtype.deduction_type_id,
                employee_id=None,
                rate_percent=rate_percent,
                amount_cents=None,
                annual_cap_cents=None,
                effective_from=date.today(),
                effective_to=None,
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()


def test_deductions_create_and_read_company_scoped():
    c1 = 1
    c2 = 2
    run1 = "pr-ded-scope-1"
    run2 = "pr-ded-scope-2"

    e1 = _seed_run_and_employee(company_id=c1, pay_period_id="pp-ded-scope-1", payroll_run_id=run1)
    e2 = _seed_run_and_employee(company_id=c2, pay_period_id="pp-ded-scope-2", payroll_run_id=run2)

    db = SessionLocal()
    try:
        db.add_all(
            [
                PayrollDeduction(
                    company_id=c1,
                    payroll_run_id=run1,
                    employee_id=e1,
                    paystub_id=None,
                    deduction_type="CPP",
                    amount_cents=1500,
                ),
                PayrollDeduction(
                    company_id=c1,
                    payroll_run_id=run1,
                    employee_id=e1,
                    paystub_id=None,
                    deduction_type="EI",
                    amount_cents=300,
                ),
                PayrollDeduction(
                    company_id=c2,
                    payroll_run_id=run2,
                    employee_id=e2,
                    paystub_id=None,
                    deduction_type="CPP",
                    amount_cents=999,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    own = client.get(f"/payroll/runs/{run1}/deductions", headers=_auth_headers(c1))
    assert own.status_code == 200, own.text
    rows = own.json()["rows"]
    assert len(rows) == 2
    assert {r["deduction_type"] for r in rows} == {"CPP", "EI"}
    assert all(r["company_id"] == c1 for r in rows)

    other = client.get(f"/payroll/runs/{run1}/deductions", headers=_auth_headers(c2))
    assert other.status_code == 404, other.text


def test_payroll_deduction_amount_nonnegative_enforced():
    company_id = 1
    run_id = "pr-ded-ck-1"
    employee_id = _seed_run_and_employee(
        company_id=company_id,
        pay_period_id="pp-ded-ck-1",
        payroll_run_id=run_id,
    )

    db = SessionLocal()
    try:
        db.add(
            PayrollDeduction(
                company_id=company_id,
                payroll_run_id=run_id,
                employee_id=employee_id,
                paystub_id=None,
                deduction_type="TAX",
                amount_cents=-1,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_paystub_deductions_are_company_scoped_and_do_not_leak():
    c1 = 1
    c2 = 2
    run1 = "pr-ded-paystub-1"
    run2 = "pr-ded-paystub-2"

    e1 = _seed_run_and_employee(company_id=c1, pay_period_id="pp-ded-paystub-1", payroll_run_id=run1)
    e2 = _seed_run_and_employee(company_id=c2, pay_period_id="pp-ded-paystub-2", payroll_run_id=run2)

    db = SessionLocal()
    try:
        p1 = Paystub(company_id=c1, payroll_run_id=run1, employee_id=e1, gross_pay_cents=10000)
        p2 = Paystub(company_id=c2, payroll_run_id=run2, employee_id=e2, gross_pay_cents=20000)
        db.add_all([p1, p2])
        db.flush()

        db.add_all(
            [
                PayrollDeduction(
                    company_id=c1,
                    payroll_run_id=run1,
                    employee_id=e1,
                    paystub_id=p1.paystub_id,
                    deduction_type="CPP",
                    amount_cents=1200,
                ),
                PayrollDeduction(
                    company_id=c2,
                    payroll_run_id=run2,
                    employee_id=e2,
                    paystub_id=p2.paystub_id,
                    deduction_type="CPP",
                    amount_cents=2200,
                ),
            ]
        )
        db.commit()
        p1_id = p1.paystub_id
    finally:
        db.close()

    own = client.get(
        f"/payroll/runs/{run1}/paystubs/{p1_id}/deductions",
        headers=_auth_headers(c1),
    )
    assert own.status_code == 200, own.text
    rows = own.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["company_id"] == c1
    assert rows[0]["amount_cents"] == 1200

    other = client.get(
        f"/payroll/runs/{run1}/paystubs/{p1_id}/deductions",
        headers=_auth_headers(c2),
    )
    assert other.status_code == 404, other.text


def test_generate_deductions_for_finalized_run_succeeds_and_is_idempotent():
    company_id = 1
    run_id = "pr-gended-1"
    _seed_finalized_run_with_items(
        company_id=company_id,
        payroll_run_id=run_id,
        pay_period_id="pp-gended-1",
    )

    paystubs = client.post(
        f"/payroll/runs/{run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert paystubs.status_code == 200, paystubs.text
    paystub_rows_before = client.get(
        f"/payroll/runs/{run_id}/paystubs",
        headers=_auth_headers(company_id),
    ).json()["rows"]
    assert len(paystub_rows_before) == 2
    assert all(r["total_deductions_cents"] == 0 for r in paystub_rows_before)
    assert all(r["net_pay_cents"] == r["gross_pay_cents"] for r in paystub_rows_before)

    first = client.post(
        f"/payroll/runs/{run_id}/deductions/generate",
        headers=_auth_headers(company_id),
    )
    assert first.status_code == 200, first.text
    b1 = first.json()
    assert b1["generated"] == 4  # 2 employees * 2 statutory deduction types
    assert b1["skipped"] == 0

    second = client.post(
        f"/payroll/runs/{run_id}/deductions/generate",
        headers=_auth_headers(company_id),
    )
    assert second.status_code == 200, second.text
    b2 = second.json()
    assert b2["generated"] == 0
    assert b2["skipped"] == 4

    rows = client.get(
        f"/payroll/runs/{run_id}/deductions",
        headers=_auth_headers(company_id),
    )
    assert rows.status_code == 200, rows.text
    data = rows.json()["rows"]
    assert len(data) == 4
    assert {r["deduction_type"] for r in data} == {"CPP", "EI"}
    assert {r["calculation_source"] for r in data} == {"STATUTORY"}

    paystub_rows_after = client.get(
        f"/payroll/runs/{run_id}/paystubs",
        headers=_auth_headers(company_id),
    ).json()["rows"]
    totals = {
        int(r["gross_pay_cents"]): (int(r["total_deductions_cents"]), int(r["net_pay_cents"]))
        for r in paystub_rows_after
    }
    assert totals[6000] == (480, 5520)
    assert totals[9600] == (768, 8832)

    paystub_rows_after_second = client.get(
        f"/payroll/runs/{run_id}/paystubs",
        headers=_auth_headers(company_id),
    ).json()["rows"]
    totals_second = {
        int(r["gross_pay_cents"]): (int(r["total_deductions_cents"]), int(r["net_pay_cents"]))
        for r in paystub_rows_after_second
    }
    assert totals_second == totals


def test_generate_deductions_is_company_scoped():
    c1 = 1
    c2 = 2
    run1 = "pr-gended-scope-1"

    _seed_finalized_run_with_items(
        company_id=c1,
        payroll_run_id=run1,
        pay_period_id="pp-gended-scope-1",
    )
    paystubs = client.post(
        f"/payroll/runs/{run1}/paystubs/generate",
        headers=_auth_headers(c1),
    )
    assert paystubs.status_code == 200, paystubs.text

    other = client.post(
        f"/payroll/runs/{run1}/deductions/generate",
        headers=_auth_headers(c2),
    )
    assert other.status_code == 404, other.text


def test_generate_deductions_from_posted_fails_with_409_immutability_reason():
    company_id = 1
    run_id = "pr-gended-posted-1"
    _seed_finalized_run_with_items(
        company_id=company_id,
        payroll_run_id=run_id,
        pay_period_id="pp-gended-posted-1",
    )

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollRun)
            .filter(PayrollRun.company_id == company_id)
            .filter(PayrollRun.payroll_run_id == run_id)
            .one()
        )
        row.status = "POSTED"
        row.posted_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    result = client.post(
        f"/payroll/runs/{run_id}/deductions/generate",
        headers=_auth_headers(company_id),
    )
    assert result.status_code == 409, result.text
    assert "POSTED and immutable" in result.json()["detail"]


def test_generate_deductions_distinguishes_statutory_and_config_sources():
    company_id = 1
    run_id = "pr-gended-source-1"
    _seed_finalized_run_with_items(
        company_id=company_id,
        payroll_run_id=run_id,
        pay_period_id="pp-gended-source-1",
    )
    _seed_custom_deduction_config(company_id=company_id, code="UNION_DUES", rate_percent=Decimal("1.0"))

    paystubs = client.post(
        f"/payroll/runs/{run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert paystubs.status_code == 200, paystubs.text

    generated = client.post(
        f"/payroll/runs/{run_id}/deductions/generate",
        headers=_auth_headers(company_id),
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["generated"] == 6  # 2 employees * (CPP + EI + UNION_DUES)

    rows = client.get(
        f"/payroll/runs/{run_id}/deductions",
        headers=_auth_headers(company_id),
    )
    assert rows.status_code == 200, rows.text
    data = rows.json()["rows"]
    assert {r["deduction_type"] for r in data} == {"CPP", "EI", "UNION_DUES"}
    assert {r["calculation_source"] for r in data if r["deduction_type"] in {"CPP", "EI"}} == {"STATUTORY"}
    assert {r["calculation_source"] for r in data if r["deduction_type"] == "UNION_DUES"} == {"CONFIG"}


def test_paystub_detail_includes_deductions():
    company_id = 1
    run_id = "pr-gended-detail-1"
    _seed_finalized_run_with_items(
        company_id=company_id,
        payroll_run_id=run_id,
        pay_period_id="pp-gended-detail-1",
    )

    paystubs = client.post(
        f"/payroll/runs/{run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert paystubs.status_code == 200, paystubs.text

    gen = client.post(
        f"/payroll/runs/{run_id}/deductions/generate",
        headers=_auth_headers(company_id),
    )
    assert gen.status_code == 200, gen.text

    list_resp = client.get(
        f"/payroll/runs/{run_id}/paystubs",
        headers=_auth_headers(company_id),
    )
    assert list_resp.status_code == 200, list_resp.text
    paystub_id = list_resp.json()["rows"][0]["paystub_id"]

    detail = client.get(
        f"/payroll/runs/{run_id}/paystubs/{paystub_id}",
        headers=_auth_headers(company_id),
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["paystub"]["paystub_id"] == paystub_id
    assert "gross_pay_cents" in body["paystub"]
    assert "total_deductions_cents" in body["paystub"]
    assert "net_pay_cents" in body["paystub"]
    assert body["paystub"]["net_pay_cents"] == body["paystub"]["gross_pay_cents"] - body["paystub"]["total_deductions_cents"]
    assert len(body["deductions"]) == 2
    assert {d["deduction_type"] for d in body["deductions"]} == {"CPP", "EI"}
    assert {d["calculation_source"] for d in body["deductions"]} == {"STATUTORY"}

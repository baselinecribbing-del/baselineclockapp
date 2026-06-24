from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.event_outbox import EventOutbox
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
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


def _seed_run_with_items(*, company_id: int, payroll_run_id: str, pay_period_id: str, status: str) -> tuple[int, int]:
    db = SessionLocal()
    try:
        e1 = Employee(company_id=company_id, name=f"Emp A {payroll_run_id}", hourly_rate_cents=3000)
        e2 = Employee(company_id=company_id, name=f"Emp B {payroll_run_id}", hourly_rate_cents=3200)
        db.add_all([e1, e2])
        db.flush()

        db.add(
            PayPeriod(
                pay_period_id=pay_period_id,
                company_id=company_id,
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 14),
                status="POSTED",
            )
        )
        db.flush()

        db.add(
            PayrollRun(
                payroll_run_id=payroll_run_id,
                company_id=company_id,
                pay_period_id=pay_period_id,
                status=status,
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
                    hours=1,
                    rate_cents=3000,
                    gross_pay_cents=3000,
                    meta={"job_id": 1},
                ),
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
                    hours=1,
                    rate_cents=3200,
                    gross_pay_cents=3200,
                    meta={"job_id": 1},
                ),
            ]
        )
        db.commit()
        return e1.id, e2.id
    finally:
        db.close()


def test_generate_paystubs_from_finalized_payroll_run_succeeds():
    company_id = 1
    payroll_run_id = "pr-paystub-finalized-1"
    _seed_run_with_items(
        company_id=company_id,
        payroll_run_id=payroll_run_id,
        pay_period_id="pp-paystub-finalized-1",
        status="FINALIZED",
    )

    r = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["payroll_run_id"] == payroll_run_id
    assert body["generated"] == 2
    assert body["skipped"] == 0

    listing = client.get(
        f"/payroll/runs/{payroll_run_id}/paystubs",
        headers=_auth_headers(company_id),
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()["rows"]
    assert len(rows) == 2
    assert all(row["delivery_status"] == "PENDING" for row in rows)
    assert all(row["sent_at"] is None for row in rows)
    assert all(row["sent_by_user_id"] is None for row in rows)
    assert all(row["total_deductions_cents"] == 0 for row in rows)
    assert all(row["net_pay_cents"] == row["gross_pay_cents"] for row in rows)
    gross_by_employee = {row["employee_id"]: row["gross_pay_cents"] for row in rows}
    # employee 1: 3000 + 6000, employee 2: 3200
    assert sorted(gross_by_employee.values()) == [3200, 9000]


def test_generate_paystubs_from_draft_fails_with_409():
    company_id = 1
    payroll_run_id = "pr-paystub-draft-1"
    _seed_run_with_items(
        company_id=company_id,
        payroll_run_id=payroll_run_id,
        pay_period_id="pp-paystub-draft-1",
        status="DRAFT",
    )

    r = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert r.status_code == 409, r.text
    assert "FINALIZED" in r.json()["detail"]


def test_generate_paystubs_from_posted_fails_with_409_immutability_reason():
    company_id = 1
    payroll_run_id = "pr-paystub-posted-1"
    _seed_run_with_items(
        company_id=company_id,
        payroll_run_id=payroll_run_id,
        pay_period_id="pp-paystub-posted-1",
        status="FINALIZED",
    )

    db = SessionLocal()
    try:
        row = (
            db.query(PayrollRun)
            .filter(PayrollRun.company_id == company_id)
            .filter(PayrollRun.payroll_run_id == payroll_run_id)
            .one()
        )
        row.status = "POSTED"
        row.posted_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    r = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert r.status_code == 409, r.text
    assert "POSTED and immutable" in r.json()["detail"]


def test_duplicate_paystub_generation_is_idempotent_for_same_run():
    company_id = 1
    payroll_run_id = "pr-paystub-idempotent-1"
    _seed_run_with_items(
        company_id=company_id,
        payroll_run_id=payroll_run_id,
        pay_period_id="pp-paystub-idempotent-1",
        status="FINALIZED",
    )

    first = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert first.status_code == 200, first.text
    assert first.json()["generated"] == 2

    second = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert second.status_code == 200, second.text
    assert second.json()["generated"] == 0
    assert second.json()["skipped"] == 2

    db = SessionLocal()
    try:
        count = (
            db.query(Paystub)
            .filter(Paystub.company_id == company_id)
            .filter(Paystub.payroll_run_id == payroll_run_id)
            .count()
        )
        assert count == 2
    finally:
        db.close()


def test_paystub_list_and_detail_are_company_scoped():
    c1 = 1
    c2 = 2
    run1 = "pr-paystub-scope-1"
    run2 = "pr-paystub-scope-2"

    _seed_run_with_items(
        company_id=c1,
        payroll_run_id=run1,
        pay_period_id="pp-paystub-scope-1",
        status="FINALIZED",
    )
    _seed_run_with_items(
        company_id=c2,
        payroll_run_id=run2,
        pay_period_id="pp-paystub-scope-2",
        status="FINALIZED",
    )

    g1 = client.post(f"/payroll/runs/{run1}/paystubs/generate", headers=_auth_headers(c1))
    assert g1.status_code == 200, g1.text
    g2 = client.post(f"/payroll/runs/{run2}/paystubs/generate", headers=_auth_headers(c2))
    assert g2.status_code == 200, g2.text

    list_own = client.get(f"/payroll/runs/{run1}/paystubs", headers=_auth_headers(c1))
    assert list_own.status_code == 200, list_own.text
    own_rows = list_own.json()["rows"]
    assert len(own_rows) == 2
    paystub_id = own_rows[0]["paystub_id"]

    detail_own = client.get(
        f"/payroll/runs/{run1}/paystubs/{paystub_id}",
        headers=_auth_headers(c1),
    )
    assert detail_own.status_code == 200, detail_own.text
    assert detail_own.json()["paystub"]["company_id"] == c1
    assert "gross_pay_cents" in detail_own.json()["paystub"]
    assert "total_deductions_cents" in detail_own.json()["paystub"]
    assert "net_pay_cents" in detail_own.json()["paystub"]

    list_other = client.get(f"/payroll/runs/{run1}/paystubs", headers=_auth_headers(c2))
    assert list_other.status_code == 404, list_other.text

    detail_other = client.get(
        f"/payroll/runs/{run1}/paystubs/{paystub_id}",
        headers=_auth_headers(c2),
    )
    assert detail_other.status_code == 404, detail_other.text


def test_mark_paystub_sent_succeeds_then_second_mark_fails_with_409():
    company_id = 1
    payroll_run_id = "pr-paystub-delivery-1"
    _seed_run_with_items(
        company_id=company_id,
        payroll_run_id=payroll_run_id,
        pay_period_id="pp-paystub-delivery-1",
        status="FINALIZED",
    )

    g = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert g.status_code == 200, g.text

    rows = client.get(
        f"/payroll/runs/{payroll_run_id}/paystubs",
        headers=_auth_headers(company_id),
    ).json()["rows"]
    paystub_id = rows[0]["paystub_id"]

    sent = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/{paystub_id}/mark_sent",
        headers=_auth_headers(company_id),
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["delivery_status"] == "SENT"
    assert body["sent_at"] is not None
    assert body["sent_by_user_id"] == "test-user"

    db = SessionLocal()
    try:
        rows = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.event_type == "PAYSTUB_MARKED_SENT")
            .filter(EventOutbox.idempotency_key == f"paystub:{paystub_id}:sent")
            .all()
        )
        assert len(rows) == 1
        payload = rows[0].payload
        assert payload["paystub_id"] == paystub_id
        assert payload["company_id"] == company_id
        assert payload["payroll_run_id"] == payroll_run_id
        assert payload["employee_id"] == body["employee_id"]
        assert payload["sent_at"] is not None
    finally:
        db.close()

    second = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/{paystub_id}/mark_sent",
        headers=_auth_headers(company_id),
    )
    assert second.status_code == 409, second.text
    assert "already marked as SENT" in second.json()["detail"]

    db2 = SessionLocal()
    try:
        rows2 = (
            db2.query(EventOutbox)
            .filter(EventOutbox.company_id == company_id)
            .filter(EventOutbox.event_type == "PAYSTUB_MARKED_SENT")
            .filter(EventOutbox.idempotency_key == f"paystub:{paystub_id}:sent")
            .all()
        )
        assert len(rows2) == 1
    finally:
        db2.close()


def test_mark_paystub_sent_is_company_scoped():
    c1 = 1
    c2 = 2
    run1 = "pr-paystub-delivery-scope-1"
    run2 = "pr-paystub-delivery-scope-2"

    _seed_run_with_items(
        company_id=c1,
        payroll_run_id=run1,
        pay_period_id="pp-paystub-delivery-scope-1",
        status="FINALIZED",
    )
    _seed_run_with_items(
        company_id=c2,
        payroll_run_id=run2,
        pay_period_id="pp-paystub-delivery-scope-2",
        status="FINALIZED",
    )

    g1 = client.post(f"/payroll/runs/{run1}/paystubs/generate", headers=_auth_headers(c1))
    assert g1.status_code == 200, g1.text

    paystub_id = client.get(
        f"/payroll/runs/{run1}/paystubs",
        headers=_auth_headers(c1),
    ).json()["rows"][0]["paystub_id"]

    other = client.post(
        f"/payroll/runs/{run1}/paystubs/{paystub_id}/mark_sent",
        headers=_auth_headers(c2),
    )
    assert other.status_code == 404, other.text

    db = SessionLocal()
    try:
        rows = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == c1)
            .filter(EventOutbox.event_type == "PAYSTUB_MARKED_SENT")
            .filter(EventOutbox.idempotency_key == f"paystub:{paystub_id}:sent")
            .all()
        )
        assert len(rows) == 0
    finally:
        db.close()


def test_list_paystubs_can_filter_by_delivery_status():
    company_id = 1
    payroll_run_id = "pr-paystub-delivery-filter-1"
    _seed_run_with_items(
        company_id=company_id,
        payroll_run_id=payroll_run_id,
        pay_period_id="pp-paystub-delivery-filter-1",
        status="FINALIZED",
    )

    g = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert g.status_code == 200, g.text

    rows = client.get(
        f"/payroll/runs/{payroll_run_id}/paystubs",
        headers=_auth_headers(company_id),
    ).json()["rows"]
    first_id = rows[0]["paystub_id"]

    sent = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/{first_id}/mark_sent",
        headers=_auth_headers(company_id),
    )
    assert sent.status_code == 200, sent.text

    pending = client.get(
        f"/payroll/runs/{payroll_run_id}/paystubs?delivery_status=PENDING",
        headers=_auth_headers(company_id),
    )
    assert pending.status_code == 200, pending.text
    pending_rows = pending.json()["rows"]
    assert len(pending_rows) == 1
    assert pending_rows[0]["delivery_status"] == "PENDING"

    sent_rows_resp = client.get(
        f"/payroll/runs/{payroll_run_id}/paystubs?delivery_status=SENT",
        headers=_auth_headers(company_id),
    )
    assert sent_rows_resp.status_code == 200, sent_rows_resp.text
    sent_rows = sent_rows_resp.json()["rows"]
    assert len(sent_rows) == 1
    assert sent_rows[0]["delivery_status"] == "SENT"


def test_paystubs_dataset_lists_rows_with_employee_and_pay_period_data():
    company_id = 3
    payroll_run_id = "pr-paystub-dataset-1"
    employee_id, _other_employee_id = _seed_run_with_items(
        company_id=company_id,
        payroll_run_id=payroll_run_id,
        pay_period_id="pp-paystub-dataset-1",
        status="FINALIZED",
    )

    generated = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert generated.status_code == 200, generated.text

    resp = client.get("/payroll/paystubs", headers=_auth_headers(company_id))
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 2

    row = next(r for r in rows if r["employee_id"] == employee_id)
    assert row["payroll_run_id"] == payroll_run_id
    assert row["employee_name"] == f"Emp A {payroll_run_id}"
    assert row["pay_period_start"] == "2026-10-01"
    assert row["pay_period_end"] == "2026-10-14"
    assert row["gross_pay_cents"] == 9000
    assert row["total_deductions_cents"] == 0
    assert row["net_pay_cents"] == 9000
    assert row["delivery_status"] == "PENDING"
    assert row["sent_at"] is None
    assert row["created_at"] is not None


def test_paystubs_dataset_supports_filters():
    company_id = 4
    payroll_run_id = "pr-paystub-dataset-filter-1"
    employee_id, other_employee_id = _seed_run_with_items(
        company_id=company_id,
        payroll_run_id=payroll_run_id,
        pay_period_id="pp-paystub-dataset-filter-1",
        status="FINALIZED",
    )

    generated = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/generate",
        headers=_auth_headers(company_id),
    )
    assert generated.status_code == 200, generated.text

    rows = client.get(
        "/payroll/paystubs",
        headers=_auth_headers(company_id),
    ).json()["rows"]
    sent_target = next(r for r in rows if r["employee_id"] == other_employee_id)

    sent = client.post(
        f"/payroll/runs/{payroll_run_id}/paystubs/{sent_target['paystub_id']}/mark_sent",
        headers=_auth_headers(company_id),
    )
    assert sent.status_code == 200, sent.text

    by_run = client.get(
        f"/payroll/paystubs?payroll_run_id={payroll_run_id}",
        headers=_auth_headers(company_id),
    )
    assert by_run.status_code == 200, by_run.text
    assert len(by_run.json()["rows"]) == 2

    by_employee = client.get(
        f"/payroll/paystubs?employee_id={employee_id}",
        headers=_auth_headers(company_id),
    )
    assert by_employee.status_code == 200, by_employee.text
    employee_rows = by_employee.json()["rows"]
    assert len(employee_rows) == 1
    assert employee_rows[0]["employee_id"] == employee_id

    sent_rows = client.get(
        "/payroll/paystubs?status=SENT",
        headers=_auth_headers(company_id),
    )
    assert sent_rows.status_code == 200, sent_rows.text
    assert len(sent_rows.json()["rows"]) == 1
    assert sent_rows.json()["rows"][0]["delivery_status"] == "SENT"

    pending_rows = client.get(
        "/payroll/paystubs?status=PENDING",
        headers=_auth_headers(company_id),
    )
    assert pending_rows.status_code == 200, pending_rows.text
    assert len(pending_rows.json()["rows"]) == 1
    assert pending_rows.json()["rows"][0]["delivery_status"] == "PENDING"


def test_paystubs_dataset_is_company_scoped():
    c1 = 5
    c2 = 6
    run1 = "pr-paystub-dataset-scope-1"
    run2 = "pr-paystub-dataset-scope-2"

    _seed_run_with_items(
        company_id=c1,
        payroll_run_id=run1,
        pay_period_id="pp-paystub-dataset-scope-1",
        status="FINALIZED",
    )
    _seed_run_with_items(
        company_id=c2,
        payroll_run_id=run2,
        pay_period_id="pp-paystub-dataset-scope-2",
        status="FINALIZED",
    )

    generated_1 = client.post(f"/payroll/runs/{run1}/paystubs/generate", headers=_auth_headers(c1))
    assert generated_1.status_code == 200, generated_1.text
    generated_2 = client.post(f"/payroll/runs/{run2}/paystubs/generate", headers=_auth_headers(c2))
    assert generated_2.status_code == 200, generated_2.text

    own = client.get("/payroll/paystubs", headers=_auth_headers(c1))
    assert own.status_code == 200, own.text
    own_rows = own.json()["rows"]
    assert len(own_rows) == 2
    assert all(row["payroll_run_id"] == run1 for row in own_rows)

    other = client.get("/payroll/paystubs", headers=_auth_headers(c2))
    assert other.status_code == 200, other.text
    other_rows = other.json()["rows"]
    assert len(other_rows) == 2
    assert all(row["payroll_run_id"] == run2 for row in other_rows)

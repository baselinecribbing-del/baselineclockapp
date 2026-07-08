"""Milestone-0 security regression: POST /payroll/runs/{id}/post authz.

Before Milestone-0 this endpoint had NO authentication and NO company scoping —
any caller who could reach the port could finalize/post any company's payroll
run (emitting the PAYROLL_RUN_POSTED outbox event). These tests pin the fix:
the endpoint now requires an authenticated principal and is company-scoped.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.pay_period import PayPeriod
from app.models.payroll_run import PayrollRun


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _seed_run(payroll_run_id: str, company_id: int) -> None:
    pay_period_id = f"pp-{payroll_run_id}"
    db = SessionLocal()
    try:
        db.add(
            PayPeriod(
                pay_period_id=pay_period_id,
                company_id=company_id,
                start_date=datetime(2026, 1, 1).date(),
                end_date=datetime(2026, 1, 8).date(),
                status="POSTED",
            )
        )
        db.add(
            PayrollRun(
                payroll_run_id=payroll_run_id,
                company_id=company_id,
                pay_period_id=pay_period_id,
                status="DRAFT",
            )
        )
        db.commit()
    finally:
        db.close()


def _headers(client: TestClient, company_id: int) -> dict:
    token = client.post(
        "/auth/token", json={"user_id": "test", "company_id": company_id}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def test_payroll_post_requires_authentication():
    _seed_run("pr-authz-unauth", company_id=1)
    client = TestClient(app)
    # No Authorization header at all -> must be rejected, not silently POSTED.
    r = client.post("/payroll/runs/pr-authz-unauth/post")
    assert r.status_code in (401, 403), r.text


def test_payroll_post_is_company_scoped():
    # Run belongs to company 1; a company-2 token must not be able to post it.
    _seed_run("pr-authz-tenant", company_id=1)
    client = TestClient(app)
    r = client.post(
        "/payroll/runs/pr-authz-tenant/post", headers=_headers(client, company_id=2)
    )
    assert r.status_code == 404, r.text  # not visible to another tenant


def test_payroll_post_succeeds_for_authorized_same_company():
    _seed_run("pr-authz-ok", company_id=1)
    client = TestClient(app)
    r = client.post(
        "/payroll/runs/pr-authz-ok/post", headers=_headers(client, company_id=1)
    )
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "POSTED"

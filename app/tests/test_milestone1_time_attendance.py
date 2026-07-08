"""Milestone-1 Time & Attendance certification tests.

Covers the required M1 behaviors for the mounted Time & Attendance scope:
  - router mount / unsafe-router-blocked assertions
  - auth + fail-closed role enforcement
  - company scoping
  - negative-hours rejection (application + reflected in behavior)
  - duplicate active clock-in rejection
  - missing clock-out handling
  - admin approval route protection

All data is created fresh per test on the local test DB (no production data).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.time_entry import TimeEntry
from app.services.auth_service import JWT_ALGORITHM, _get_jwt_secret

client = TestClient(app)

COMPANY_A = 71001
COMPANY_B = 71002


def _headers(company_id: int, role: str = "MANAGER", user_id: str = "m1-user") -> dict:
    resp = client.post(
        "/auth/token", json={"user_id": user_id, "company_id": company_id, "role": role}
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _roleless_token(company_id: int) -> str:
    """Forge a valid-signature token that carries NO role claim (fail-closed check)."""
    now = datetime.now(timezone.utc)
    payload = {"sub": "no-role", "company_id": int(company_id), "exp": now + timedelta(hours=1)}
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def _seed_worker(company_id: int):
    """Create an employee + geofence-free job + scope; return their ids."""
    from app.models.employee import Employee
    from app.models.job import Job
    from app.models.scope import Scope

    db = SessionLocal()
    try:
        emp = Employee(company_id=company_id, name="Clock Worker", is_active=True, hourly_rate_cents=3000)
        job = Job(company_id=company_id, name="Clock Job", is_active=True)  # no site_lat/lng -> no GPS gate
        db.add_all([emp, job])
        db.flush()
        scope = Scope(company_id=company_id, name="Clock Scope", is_active=True, job_id=int(job.id))
        db.add(scope)
        db.commit()
        return int(emp.id), int(job.id), int(scope.id)
    finally:
        db.close()


def _clock_in(company_id: int, emp_id: int, job_id: int, scope_id: int, started_at=None, role="MANAGER"):
    body = {"employee_id": emp_id, "job_id": job_id, "scope_id": scope_id}
    if started_at is not None:
        body["started_at"] = started_at.isoformat()
    return client.post("/time_entries/clock_in", headers=_headers(company_id, role=role), json=body)


# --------------------------------------------------------------------------- #
# 1. Router mount / unsafe-router-blocked
# --------------------------------------------------------------------------- #
def test_m1_routers_are_mounted():
    # Clean M1 Time & Attendance slice: the T&A surface is live via the base
    # time_entries router (clock in/out + approve/reject) plus payroll/auth.
    # The workforce superset routers (crews/company/credentials/employee-self-service)
    # are intentionally NOT part of this slice — they belong to the scaffold
    # branch (Release 1 / M2), so they are deliberately absent here.
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert any(p.startswith("/time_entries") for p in paths)
    assert any(p.startswith("/payroll") for p in paths)
    assert any(p.startswith("/auth") for p in paths)
    # scaffold routers must NOT be present in the clean slice
    assert not any(p.startswith("/crews") for p in paths)
    assert not any(p.startswith("/employee-self-service") for p in paths)


def test_unsafe_routers_are_not_mounted():
    """Payroll finalize/T4/tax and billing surfaces stay OFF in M1."""
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert not any(p.startswith("/invoices") for p in paths)
    assert not any(p.startswith("/ledger") for p in paths)
    assert not any(p.startswith("/waste-bin") for p in paths)
    assert not any(p.startswith("/waste_bins") for p in paths)
    assert not any(p.startswith("/job-documents") for p in paths)
    # payroll T4 slip routes must not be exposed
    assert not any("/payroll/t4s" in p for p in paths)


# --------------------------------------------------------------------------- #
# 2. Auth + fail-closed role
# --------------------------------------------------------------------------- #
def test_clock_in_requires_authentication():
    emp_id, job_id, scope_id = _seed_worker(COMPANY_A)
    r = client.post(
        "/time_entries/clock_in",
        json={"employee_id": emp_id, "job_id": job_id, "scope_id": scope_id},
    )
    assert r.status_code in (401, 403), r.text


def test_roleless_token_is_rejected_on_role_guarded_route():
    """Fail-closed role: a signed token with no role claim cannot approve."""
    emp_id, job_id, scope_id = _seed_worker(COMPANY_A)
    token = _roleless_token(COMPANY_A)
    headers = {"Authorization": f"Bearer {token}", "X-Company-Id": str(COMPANY_A)}
    r = client.post("/time_entries/some-id/approve", headers=headers)
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- #
# 3. Company scoping
# --------------------------------------------------------------------------- #
def test_clock_in_company_scope_mismatch_is_rejected():
    emp_id, job_id, scope_id = _seed_worker(COMPANY_A)
    # token for company A, but X-Company-Id header claims company B
    token = client.post(
        "/auth/token", json={"user_id": "x", "company_id": COMPANY_A, "role": "MANAGER"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Company-Id": str(COMPANY_B)}
    r = client.post(
        "/time_entries/clock_in",
        headers=headers,
        json={"employee_id": emp_id, "job_id": job_id, "scope_id": scope_id},
    )
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- #
# 4. Negative-hours rejection
# --------------------------------------------------------------------------- #
def test_clock_out_before_clock_in_is_rejected():
    emp_id, job_id, scope_id = _seed_worker(COMPANY_A)
    started = datetime.now(timezone.utc)
    ci = _clock_in(COMPANY_A, emp_id, job_id, scope_id, started_at=started)
    assert ci.status_code == 200, ci.text
    # ended_at one hour BEFORE started_at -> negative duration -> 409
    r = client.post(
        "/time_entries/clock_out",
        headers=_headers(COMPANY_A),
        json={"employee_id": emp_id, "ended_at": (started - timedelta(hours=1)).isoformat()},
    )
    assert r.status_code == 409, r.text
    assert "negative" in r.text.lower() or "earlier" in r.text.lower()


# --------------------------------------------------------------------------- #
# 5. Duplicate active clock-in rejection
# --------------------------------------------------------------------------- #
def test_duplicate_active_clock_in_is_rejected():
    emp_id, job_id, scope_id = _seed_worker(COMPANY_A)
    first = _clock_in(COMPANY_A, emp_id, job_id, scope_id)
    assert first.status_code == 200, first.text
    second = _clock_in(COMPANY_A, emp_id, job_id, scope_id)
    assert second.status_code == 409, second.text


# --------------------------------------------------------------------------- #
# 6. Missing clock-out handling (no active entry)
# --------------------------------------------------------------------------- #
def test_clock_out_without_active_entry_is_rejected():
    emp_id, _, _ = _seed_worker(COMPANY_A)
    r = client.post(
        "/time_entries/clock_out",
        headers=_headers(COMPANY_A),
        json={"employee_id": emp_id},
    )
    assert r.status_code == 409, r.text


# --------------------------------------------------------------------------- #
# 7. Admin approval route protection + happy path
# --------------------------------------------------------------------------- #
def _completed_entry(company_id: int, emp_id: int, job_id: int, scope_id: int) -> str:
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    ci = _clock_in(company_id, emp_id, job_id, scope_id, started_at=started)
    assert ci.status_code == 200, ci.text
    co = client.post(
        "/time_entries/clock_out",
        headers=_headers(company_id),
        json={"employee_id": emp_id, "ended_at": datetime.now(timezone.utc).isoformat()},
    )
    assert co.status_code == 200, co.text
    return co.json()["time_entry_id"]


def test_approval_requires_manager_role():
    emp_id, job_id, scope_id = _seed_worker(COMPANY_A)
    entry_id = _completed_entry(COMPANY_A, emp_id, job_id, scope_id)
    # EMPLOYEE role cannot approve
    r_emp = client.post(f"/time_entries/{entry_id}/approve", headers=_headers(COMPANY_A, role="EMPLOYEE"))
    assert r_emp.status_code == 403, r_emp.text
    # MANAGER can approve
    r_mgr = client.post(f"/time_entries/{entry_id}/approve", headers=_headers(COMPANY_A, role="MANAGER"))
    assert r_mgr.status_code == 200, r_mgr.text
    assert r_mgr.json()["approval_status"] == "approved"


def test_negative_duration_blocked_at_db_layer():
    """Defense-in-depth: the DB CHECK constraint rejects a negative-duration row."""
    import sqlalchemy
    from app.models.job import Job  # noqa: F401  (ensure metadata loaded)

    db = SessionLocal()
    try:
        entry = TimeEntry(
            time_entry_id="m1-neg-db",
            company_id=COMPANY_A,
            employee_id=1,
            job_id=1,
            scope_id=1,
            started_at=datetime(2026, 1, 2, 10, 0, 0),
            ended_at=datetime(2026, 1, 2, 9, 0, 0),
            status="completed",
            approval_status="pending",
        )
        db.add(entry)
        raised = False
        try:
            db.commit()
        except sqlalchemy.exc.IntegrityError:
            raised = True
            db.rollback()
        assert raised, "DB CHECK constraint did not reject negative duration"
    finally:
        db.close()

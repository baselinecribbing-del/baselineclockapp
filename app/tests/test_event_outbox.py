from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.event_outbox import EventOutbox

client = TestClient(app)


def _auth_headers(company_id: int) -> dict:
    r = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {token}"}


def test_clock_out_creates_outbox_event(employee_factory, job_factory, scope_factory):
    company_id = 1
    headers = _auth_headers(company_id)

    e = employee_factory(company_id=company_id)
    j = job_factory(company_id=company_id)
    s = scope_factory(company_id=company_id, job_id=j.id)

    now = datetime.now(timezone.utc)

    r_in = client.post(
        "/time_entries/clock_in",
        json={"employee_id": e.id, "job_id": j.id, "scope_id": s.id, "started_at": now.isoformat()},
        headers=headers,
    )
    assert r_in.status_code == 200, r_in.text

    r_out = client.post(
        "/time_entries/clock_out",
        json={"employee_id": e.id, "ended_at": now.isoformat()},
        headers=headers,
    )
    assert r_out.status_code == 200, r_out.text
    te_id = r_out.json()["time_entry_id"]

    db = SessionLocal()
    try:
        rows = (
            db.query(EventOutbox)
            .filter(
                EventOutbox.company_id == company_id,
                EventOutbox.event_type == "TIME_ENTRY_CLOCKED_OUT",
                EventOutbox.idempotency_key == f"time_entry:{te_id}:clock_out",
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].payload["time_entry_id"] == te_id
        assert rows[0].processed is False
    finally:
        db.close()


def test_outbox_is_tenant_scoped(employee_factory, job_factory, scope_factory):
    c1 = 1
    c2 = 2

    e1 = employee_factory(company_id=c1)
    j1 = job_factory(company_id=c1)
    s1 = scope_factory(company_id=c1, job_id=j1.id)

    e2 = employee_factory(company_id=c2)
    j2 = job_factory(company_id=c2)
    s2 = scope_factory(company_id=c2, job_id=j2.id)

    now = datetime.now(timezone.utc)

    r1_in = client.post(
        "/time_entries/clock_in",
        json={"employee_id": e1.id, "job_id": j1.id, "scope_id": s1.id, "started_at": now.isoformat()},
        headers=_auth_headers(c1),
    )
    assert r1_in.status_code == 200, r1_in.text
    r1_out = client.post(
        "/time_entries/clock_out",
        json={"employee_id": e1.id, "ended_at": now.isoformat()},
        headers=_auth_headers(c1),
    )
    assert r1_out.status_code == 200, r1_out.text

    r2_in = client.post(
        "/time_entries/clock_in",
        json={"employee_id": e2.id, "job_id": j2.id, "scope_id": s2.id, "started_at": now.isoformat()},
        headers=_auth_headers(c2),
    )
    assert r2_in.status_code == 200, r2_in.text
    r2_out = client.post(
        "/time_entries/clock_out",
        json={"employee_id": e2.id, "ended_at": now.isoformat()},
        headers=_auth_headers(c2),
    )
    assert r2_out.status_code == 200, r2_out.text

    db = SessionLocal()
    try:
        c1_rows = db.query(EventOutbox).filter(EventOutbox.company_id == c1).all()
        c2_rows = db.query(EventOutbox).filter(EventOutbox.company_id == c2).all()
        assert len(c1_rows) == 1
        assert len(c2_rows) == 1
        assert c1_rows[0].company_id != c2_rows[0].company_id
    finally:
        db.close()


def test_no_outbox_row_when_clock_out_fails(employee_factory):
    company_id = 1
    headers = _auth_headers(company_id)

    e = employee_factory(company_id=company_id)
    now = datetime.now(timezone.utc)

    # no clock_in -> should fail
    r_out = client.post(
        "/time_entries/clock_out",
        json={"employee_id": e.id, "ended_at": now.isoformat()},
        headers=headers,
    )
    assert r_out.status_code == 409, r_out.text

    db = SessionLocal()
    try:
        rows = (
            db.query(EventOutbox)
            .filter(
                EventOutbox.company_id == company_id,
                EventOutbox.event_type == "TIME_ENTRY_CLOCKED_OUT",
            )
            .all()
        )
        assert len(rows) == 0
    finally:
        db.close()

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth_headers(company_id: int) -> dict:
    r = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {token}"}


def test_list_time_entries_scoped_to_company(employee_factory, job_factory, scope_factory):
    c1 = 1
    c2 = 2

    # company 1 setup
    e1 = employee_factory(company_id=c1)
    j1 = job_factory(company_id=c1)
    s1 = scope_factory(company_id=c1, job_id=j1.id)

    # company 2 setup
    e2 = employee_factory(company_id=c2)
    j2 = job_factory(company_id=c2)
    s2 = scope_factory(company_id=c2, job_id=j2.id)

    now = datetime.now(timezone.utc)

    # create one entry in each company
    r1 = client.post(
        "/time_entries/clock_in",
        json={"employee_id": e1.id, "job_id": j1.id, "scope_id": s1.id, "started_at": now.isoformat()},
        headers=_auth_headers(c1),
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/time_entries/clock_in",
        json={"employee_id": e2.id, "job_id": j2.id, "scope_id": s2.id, "started_at": now.isoformat()},
        headers=_auth_headers(c2),
    )
    assert r2.status_code == 200, r2.text

    # list company 1 -> must not see company 2
    listing_1 = client.get("/time_entries", headers=_auth_headers(c1))
    assert listing_1.status_code == 200, listing_1.text
    data_1 = listing_1.json()
    assert isinstance(data_1, list)
    assert len(data_1) == 1
    assert data_1[0]["company_id"] == c1
    assert data_1[0]["employee_id"] == e1.id

    # list company 2 -> must not see company 1
    listing_2 = client.get("/time_entries", headers=_auth_headers(c2))
    assert listing_2.status_code == 200, listing_2.text
    data_2 = listing_2.json()
    assert isinstance(data_2, list)
    assert len(data_2) == 1
    assert data_2[0]["company_id"] == c2
    assert data_2[0]["employee_id"] == e2.id


def test_list_time_entries_filters_and_pagination(employee_factory, job_factory, scope_factory):
    company_id = 1
    headers = _auth_headers(company_id)

    e1 = employee_factory(company_id=company_id, name="E1")
    e2 = employee_factory(company_id=company_id, name="E2")
    j = job_factory(company_id=company_id)
    s = scope_factory(company_id=company_id, job_id=j.id)

    now = datetime.now(timezone.utc)
    t1 = now - timedelta(hours=2)
    t2 = now - timedelta(hours=1)

    # create 2 entries (one per employee to avoid active-unique collisions)
    r1 = client.post(
        "/time_entries/clock_in",
        json={"employee_id": e1.id, "job_id": j.id, "scope_id": s.id, "started_at": t1.isoformat()},
        headers=headers,
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/time_entries/clock_in",
        json={"employee_id": e2.id, "job_id": j.id, "scope_id": s.id, "started_at": t2.isoformat()},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text

    # filter by employee_id
    only_e1 = client.get(
        "/time_entries",
        params={"employee_id": e1.id},
        headers=headers,
    )
    assert only_e1.status_code == 200, only_e1.text
    data = only_e1.json()
    assert len(data) == 1
    assert data[0]["employee_id"] == e1.id

    # started_at range filter (should include only t2)
    from_t = (now - timedelta(hours=1, minutes=30)).isoformat()
    to_t = now.isoformat()
    only_recent = client.get(
        "/time_entries",
        params={"started_at_from": from_t, "started_at_to": to_t},
        headers=headers,
    )
    assert only_recent.status_code == 200, only_recent.text
    data = only_recent.json()
    assert len(data) == 1
    assert data[0]["employee_id"] == e2.id

    # pagination: limit=1 should return one row, offset=1 should return the other
    page1 = client.get("/time_entries?limit=1&offset=0", headers=headers)
    assert page1.status_code == 200, page1.text
    d1 = page1.json()
    assert len(d1) == 1

    page2 = client.get("/time_entries?limit=1&offset=1", headers=headers)
    assert page2.status_code == 200, page2.text
    d2 = page2.json()
    assert len(d2) == 1

    assert d1[0]["time_entry_id"] != d2[0]["time_entry_id"]



def test_list_time_entries_rejects_invalid_status(employee_factory, job_factory, scope_factory):
    company_id = 1
    headers = _auth_headers(company_id)

    e1 = employee_factory(company_id=company_id)
    j = job_factory(company_id=company_id)
    s = scope_factory(company_id=company_id, job_id=j.id)

    now = datetime.now(timezone.utc)

    r1 = client.post(
        "/time_entries/clock_in",
        json={"employee_id": e1.id, "job_id": j.id, "scope_id": s.id, "started_at": now.isoformat()},
        headers=headers,
    )
    assert r1.status_code == 200, r1.text

    bad = client.get(
        "/time_entries",
        params={"status": "garbage"},
        headers=headers,
    )
    assert bad.status_code == 422, bad.text


def test_list_time_entries_filters_by_status(employee_factory, job_factory, scope_factory):
    company_id = 1
    headers = _auth_headers(company_id)

    e_active = employee_factory(company_id=company_id)
    e_completed = employee_factory(company_id=company_id)
    j = job_factory(company_id=company_id)
    s = scope_factory(company_id=company_id, job_id=j.id)

    now = datetime.now(timezone.utc)

    r_active = client.post(
        "/time_entries/clock_in",
        json={
            "employee_id": e_active.id,
            "job_id": j.id,
            "scope_id": s.id,
            "started_at": (now - timedelta(hours=2)).isoformat(),
        },
        headers=headers,
    )
    assert r_active.status_code == 200, r_active.text

    r_completed_in = client.post(
        "/time_entries/clock_in",
        json={
            "employee_id": e_completed.id,
            "job_id": j.id,
            "scope_id": s.id,
            "started_at": (now - timedelta(hours=1)).isoformat(),
        },
        headers=headers,
    )
    assert r_completed_in.status_code == 200, r_completed_in.text

    r_completed_out = client.post(
        "/time_entries/clock_out",
        json={"employee_id": e_completed.id, "ended_at": now.isoformat()},
        headers=headers,
    )
    assert r_completed_out.status_code == 200, r_completed_out.text

    active_listing = client.get(
        "/time_entries",
        params={"status": "active"},
        headers=headers,
    )
    assert active_listing.status_code == 200, active_listing.text
    active_data = active_listing.json()
    assert len(active_data) == 1
    assert active_data[0]["employee_id"] == e_active.id
    assert active_data[0]["status"] == "active"

    completed_listing = client.get(
        "/time_entries",
        params={"status": "completed"},
        headers=headers,
    )
    assert completed_listing.status_code == 200, completed_listing.text
    completed_data = completed_listing.json()
    assert len(completed_data) == 1
    assert completed_data[0]["employee_id"] == e_completed.id
    assert completed_data[0]["status"] == "completed"

def test_completed_time_entry_defaults_to_pending_approval(employee_factory, job_factory, scope_factory):
    company_id = 70001
    headers = _auth_headers(company_id)

    employee = employee_factory(company_id=company_id)
    job = job_factory(company_id=company_id)
    scope = scope_factory(company_id=company_id, job_id=job.id)

    started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    ended_at = datetime.now(timezone.utc) - timedelta(hours=1)

    r_in = client.post(
        "/time_entries/clock_in",
        json={
            "employee_id": employee.id,
            "job_id": job.id,
            "scope_id": scope.id,
            "started_at": started_at.isoformat(),
        },
        headers=headers,
    )
    assert r_in.status_code == 200, r_in.text

    r_out = client.post(
        "/time_entries/clock_out",
        json={"employee_id": employee.id, "ended_at": ended_at.isoformat()},
        headers=headers,
    )
    assert r_out.status_code == 200, r_out.text
    payload = r_out.json()
    assert payload["status"] == "completed"
    assert payload["approval_status"] == "pending"


def test_list_time_entries_filters_by_approval_status(employee_factory, job_factory, scope_factory):
    company_id = 70002
    headers = _auth_headers(company_id)

    employee_approved = employee_factory(company_id=company_id)
    employee_pending = employee_factory(company_id=company_id)
    job = job_factory(company_id=company_id)
    scope = scope_factory(company_id=company_id, job_id=job.id)

    start_1 = datetime.now(timezone.utc) - timedelta(hours=4)
    end_1 = datetime.now(timezone.utc) - timedelta(hours=3)
    start_2 = datetime.now(timezone.utc) - timedelta(hours=2)
    end_2 = datetime.now(timezone.utc) - timedelta(hours=1)

    r1_in = client.post(
        "/time_entries/clock_in",
        json={
            "employee_id": employee_approved.id,
            "job_id": job.id,
            "scope_id": scope.id,
            "started_at": start_1.isoformat(),
        },
        headers=headers,
    )
    assert r1_in.status_code == 200, r1_in.text

    r1_out = client.post(
        "/time_entries/clock_out",
        json={"employee_id": employee_approved.id, "ended_at": end_1.isoformat()},
        headers=headers,
    )
    assert r1_out.status_code == 200, r1_out.text
    time_entry_id = r1_out.json()["time_entry_id"]

    approved = client.post(f"/time_entries/{time_entry_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text

    r2_in = client.post(
        "/time_entries/clock_in",
        json={
            "employee_id": employee_pending.id,
            "job_id": job.id,
            "scope_id": scope.id,
            "started_at": start_2.isoformat(),
        },
        headers=headers,
    )
    assert r2_in.status_code == 200, r2_in.text

    r2_out = client.post(
        "/time_entries/clock_out",
        json={"employee_id": employee_pending.id, "ended_at": end_2.isoformat()},
        headers=headers,
    )
    assert r2_out.status_code == 200, r2_out.text

    approved_listing = client.get(
        "/time_entries",
        params={"approval_status": "approved"},
        headers=headers,
    )
    assert approved_listing.status_code == 200, approved_listing.text
    approved_data = approved_listing.json()
    assert len(approved_data) == 1
    assert approved_data[0]["employee_id"] == employee_approved.id
    assert approved_data[0]["approval_status"] == "approved"

    pending_listing = client.get(
        "/time_entries",
        params={"approval_status": "pending"},
        headers=headers,
    )
    assert pending_listing.status_code == 200, pending_listing.text
    pending_data = pending_listing.json()
    assert len(pending_data) >= 1
    assert any(row["employee_id"] == employee_pending.id and row["approval_status"] == "pending" for row in pending_data)


def test_approve_completed_time_entry_records_audit_fields(employee_factory, job_factory, scope_factory):
    company_id = 70003
    token_resp = client.post("/auth/token", json={"user_id": "manager-1", "company_id": company_id})
    assert token_resp.status_code == 200, token_resp.text
    headers = {
        "X-Company-Id": str(company_id),
        "Authorization": f"Bearer {token_resp.json()['access_token']}",
    }

    employee = employee_factory(company_id=company_id)
    job = job_factory(company_id=company_id)
    scope = scope_factory(company_id=company_id, job_id=job.id)

    started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    ended_at = datetime.now(timezone.utc) - timedelta(hours=1)

    r_in = client.post(
        "/time_entries/clock_in",
        json={
            "employee_id": employee.id,
            "job_id": job.id,
            "scope_id": scope.id,
            "started_at": started_at.isoformat(),
        },
        headers=headers,
    )
    assert r_in.status_code == 200, r_in.text

    r_out = client.post(
        "/time_entries/clock_out",
        json={"employee_id": employee.id, "ended_at": ended_at.isoformat()},
        headers=headers,
    )
    assert r_out.status_code == 200, r_out.text
    time_entry_id = r_out.json()["time_entry_id"]

    approved = client.post(f"/time_entries/{time_entry_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    payload = approved.json()
    assert payload["approval_status"] == "approved"
    assert payload["approved_by_user_id"] == "manager-1"
    assert payload["approved_at"] is not None


def test_reject_completed_time_entry_records_note_and_blocks_active_entry(employee_factory, job_factory, scope_factory):
    company_id = 70004
    token_resp = client.post("/auth/token", json={"user_id": "manager-2", "company_id": company_id})
    assert token_resp.status_code == 200, token_resp.text
    headers = {
        "X-Company-Id": str(company_id),
        "Authorization": f"Bearer {token_resp.json()['access_token']}",
    }

    employee_completed = employee_factory(company_id=company_id)
    employee_active = employee_factory(company_id=company_id)
    job = job_factory(company_id=company_id)
    scope = scope_factory(company_id=company_id, job_id=job.id)

    started_completed = datetime.now(timezone.utc) - timedelta(hours=2)
    ended_completed = datetime.now(timezone.utc) - timedelta(hours=1)
    started_active = datetime.now(timezone.utc) - timedelta(minutes=30)

    r_in_completed = client.post(
        "/time_entries/clock_in",
        json={
            "employee_id": employee_completed.id,
            "job_id": job.id,
            "scope_id": scope.id,
            "started_at": started_completed.isoformat(),
        },
        headers=headers,
    )
    assert r_in_completed.status_code == 200, r_in_completed.text

    r_out_completed = client.post(
        "/time_entries/clock_out",
        json={"employee_id": employee_completed.id, "ended_at": ended_completed.isoformat()},
        headers=headers,
    )
    assert r_out_completed.status_code == 200, r_out_completed.text
    completed_time_entry_id = r_out_completed.json()["time_entry_id"]

    rejected = client.post(
        f"/time_entries/{completed_time_entry_id}/reject",
        json={"approval_note": "needs correction"},
        headers=headers,
    )
    assert rejected.status_code == 200, rejected.text
    rejected_payload = rejected.json()
    assert rejected_payload["approval_status"] == "rejected"
    assert rejected_payload["rejected_by_user_id"] == "manager-2"
    assert rejected_payload["approval_note"] == "needs correction"

    r_in_active = client.post(
        "/time_entries/clock_in",
        json={
            "employee_id": employee_active.id,
            "job_id": job.id,
            "scope_id": scope.id,
            "started_at": started_active.isoformat(),
        },
        headers=headers,
    )
    assert r_in_active.status_code == 200, r_in_active.text
    active_time_entry_id = r_in_active.json()["time_entry_id"]

    reject_active = client.post(
        f"/time_entries/{active_time_entry_id}/reject",
        json={"approval_note": "cannot reject active"},
        headers=headers,
    )
    assert reject_active.status_code == 409, reject_active.text
    assert "Only completed time entries can be approved or rejected" in reject_active.json()["detail"]

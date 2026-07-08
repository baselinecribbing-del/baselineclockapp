from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "foreman") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_employee(company_id: int, suffix: str) -> int:
    db = SessionLocal()
    try:
        row = Employee(company_id=company_id, name=f"Emp {suffix}", is_active=True, hourly_rate_cents=3200)
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def _seed_job_scope(company_id: int, suffix: str) -> tuple[int, int]:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"Job {suffix}", is_active=True)
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Scope {suffix}", is_active=True)
        db.add(scope)
        db.commit()

        return int(job.id), int(scope.id)
    finally:
        db.close()


def test_crew_groups_create_list_members_add_remove_and_company_scoping():
    c1 = 9101
    c2 = 9102

    e1 = _seed_employee(c1, "A")
    e2 = _seed_employee(c1, "B")
    _seed_employee(c2, "C")

    create = client.post(
        "/foundations/crew-groups",
        headers=_auth_headers(c1, user_id="foreman-a"),
        json={"name": "Forming Team"},
    )
    assert create.status_code == 200, create.text
    group = create.json()
    group_id = group["crew_group_id"]
    assert group["name"] == "Forming Team"
    assert group["created_by_user_id"] == "foreman-a"

    list_c1 = client.get("/foundations/crew-groups", headers=_auth_headers(c1))
    assert list_c1.status_code == 200, list_c1.text
    assert len(list_c1.json()) == 1

    list_c2 = client.get("/foundations/crew-groups", headers=_auth_headers(c2))
    assert list_c2.status_code == 200, list_c2.text
    assert list_c2.json() == []

    add_1 = client.post(
        f"/foundations/crew-groups/{group_id}/members",
        headers=_auth_headers(c1),
        json={"employee_id": e1},
    )
    assert add_1.status_code == 200, add_1.text

    add_2 = client.post(
        f"/foundations/crew-groups/{group_id}/members",
        headers=_auth_headers(c1),
        json={"employee_id": e2},
    )
    assert add_2.status_code == 200, add_2.text

    duplicate = client.post(
        f"/foundations/crew-groups/{group_id}/members",
        headers=_auth_headers(c1),
        json={"employee_id": e1},
    )
    assert duplicate.status_code == 409, duplicate.text

    members = client.get(
        f"/foundations/crew-groups/{group_id}/members",
        headers=_auth_headers(c1),
    )
    assert members.status_code == 200, members.text
    member_rows = members.json()
    assert {row["employee_id"] for row in member_rows} == {e1, e2}

    remove = client.delete(
        f"/foundations/crew-groups/{group_id}/members/{e2}",
        headers=_auth_headers(c1),
    )
    assert remove.status_code == 200, remove.text
    assert remove.json()["ok"] is True

    members_after = client.get(
        f"/foundations/crew-groups/{group_id}/members",
        headers=_auth_headers(c1),
    )
    assert members_after.status_code == 200
    assert {row["employee_id"] for row in members_after.json()} == {e1}

    c2_read = client.get(
        f"/foundations/crew-groups/{group_id}/members",
        headers=_auth_headers(c2),
    )
    assert c2_read.status_code == 404


def test_crew_group_assign_creates_assignments_for_all_members_and_is_idempotent():
    company_id = 9201
    job_id, scope_id = _seed_job_scope(company_id, "GA")
    e1 = _seed_employee(company_id, "GA1")
    e2 = _seed_employee(company_id, "GA2")

    group_resp = client.post(
        "/foundations/crew-groups",
        headers=_auth_headers(company_id, user_id="supervisor-1"),
        json={"name": "Concrete Crew"},
    )
    assert group_resp.status_code == 200, group_resp.text
    group_id = group_resp.json()["crew_group_id"]

    for employee_id in [e1, e2]:
        add_resp = client.post(
            f"/foundations/crew-groups/{group_id}/members",
            headers=_auth_headers(company_id),
            json={"employee_id": employee_id},
        )
        assert add_resp.status_code == 200, add_resp.text

    assign_payload = {
        "job_id": job_id,
        "scope_id": scope_id,
        "assigned_date": date(2026, 3, 7).isoformat(),
        "assignment_notes": "Pour slab prep",
    }

    assign_1 = client.post(
        f"/foundations/crew-groups/{group_id}/assign",
        headers=_auth_headers(company_id, user_id="supervisor-1"),
        json=assign_payload,
    )
    assert assign_1.status_code == 200, assign_1.text
    body_1 = assign_1.json()
    assert body_1["created_count"] == 2
    assert len(body_1["assignments"]) == 2
    assert {row["employee_id"] for row in body_1["assignments"]} == {e1, e2}

    assign_2 = client.post(
        f"/foundations/crew-groups/{group_id}/assign",
        headers=_auth_headers(company_id, user_id="supervisor-2"),
        json=assign_payload,
    )
    assert assign_2.status_code == 200, assign_2.text
    body_2 = assign_2.json()
    assert body_2["created_count"] == 0
    assert len(body_2["assignments"]) == 2

    listing = client.get(
        "/foundations/crew-assignments",
        headers=_auth_headers(company_id),
        params={
            "job_id": job_id,
            "scope_id": scope_id,
            "assigned_date": assign_payload["assigned_date"],
        },
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 2
    assert {row["employee_id"] for row in rows} == {e1, e2}

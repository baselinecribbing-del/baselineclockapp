from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.crew_member import CrewMember
from app.models.employee import Employee

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _seed_employee(company_id: int, name: str) -> int:
    db = SessionLocal()
    try:
        row = Employee(company_id=company_id, name=name, legal_name=name, is_active=True)
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def test_crews_create_list_get_members_and_scoping():
    c1 = 51001
    c2 = 51002

    supervisor_id = _seed_employee(c1, "Supervisor")
    member_id = _seed_employee(c1, "Worker One")

    create = client.post(
        "/crews",
        headers=_auth_headers(c1),
        json={"name": "Alpha Crew", "supervisor_employee_id": supervisor_id, "is_active": True},
    )
    assert create.status_code == 200, create.text
    crew = create.json()
    crew_id = crew["crew_id"]

    listing = client.get("/crews", headers=_auth_headers(c1))
    assert listing.status_code == 200
    assert any(row["crew_id"] == crew_id for row in listing.json())

    add_member = client.post(
        f"/crews/{crew_id}/members",
        headers=_auth_headers(c1),
        json={"employee_id": member_id},
    )
    assert add_member.status_code == 200, add_member.text

    detail = client.get(f"/crews/{crew_id}", headers=_auth_headers(c1))
    assert detail.status_code == 200
    body = detail.json()
    assert body["crew"]["crew_id"] == crew_id
    assert len(body["members"]) == 1
    assert body["members"][0]["employee_id"] == member_id

    cross_company = client.get(f"/crews/{crew_id}", headers=_auth_headers(c2))
    assert cross_company.status_code == 404


def test_crew_membership_active_uniqueness_and_readd_after_remove():
    company_id = 51003
    member_id = _seed_employee(company_id, "Worker Two")

    create_crew = client.post(
        "/crews",
        headers=_auth_headers(company_id),
        json={"name": "Bravo Crew"},
    )
    assert create_crew.status_code == 200
    crew_id = create_crew.json()["crew_id"]

    first_add = client.post(
        f"/crews/{crew_id}/members",
        headers=_auth_headers(company_id),
        json={"employee_id": member_id},
    )
    assert first_add.status_code == 200

    duplicate_add = client.post(
        f"/crews/{crew_id}/members",
        headers=_auth_headers(company_id),
        json={"employee_id": member_id},
    )
    assert duplicate_add.status_code == 409

    remove = client.delete(f"/crews/{crew_id}/members/{member_id}", headers=_auth_headers(company_id))
    assert remove.status_code == 200
    assert remove.json()["ok"] is True

    readd = client.post(
        f"/crews/{crew_id}/members",
        headers=_auth_headers(company_id),
        json={"employee_id": member_id},
    )
    assert readd.status_code == 200


def test_crew_members_delete_requires_active_member():
    company_id = 51004
    member_id = _seed_employee(company_id, "Worker Three")

    create_crew = client.post(
        "/crews",
        headers=_auth_headers(company_id),
        json={"name": "Charlie Crew"},
    )
    assert create_crew.status_code == 200
    crew_id = create_crew.json()["crew_id"]

    missing = client.delete(f"/crews/{crew_id}/members/{member_id}", headers=_auth_headers(company_id))
    assert missing.status_code == 404


def test_db_level_active_membership_unique_index_guard():
    company_id = 51005
    employee_id = _seed_employee(company_id, "Worker Four")

    create_crew = client.post(
        "/crews",
        headers=_auth_headers(company_id),
        json={"name": "Delta Crew"},
    )
    assert create_crew.status_code == 200
    crew_id = create_crew.json()["crew_id"]

    db = SessionLocal()
    try:
        db.add(CrewMember(company_id=company_id, crew_id=crew_id, employee_id=employee_id))
        db.commit()

        db.add(CrewMember(company_id=company_id, crew_id=crew_id, employee_id=employee_id))
        try:
            db.commit()
            assert False, "expected unique active membership index violation"
        except Exception:
            db.rollback()

        existing = (
            db.query(CrewMember)
            .filter(CrewMember.company_id == company_id, CrewMember.crew_id == crew_id, CrewMember.employee_id == employee_id)
            .order_by(CrewMember.assigned_at.asc())
            .all()
        )
        existing[0].removed_at = datetime.now(timezone.utc)
        db.add(existing[0])
        db.commit()

        db.add(CrewMember(company_id=company_id, crew_id=crew_id, employee_id=employee_id))
        db.commit()
    finally:
        db.close()

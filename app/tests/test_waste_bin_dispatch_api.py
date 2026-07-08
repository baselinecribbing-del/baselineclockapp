from datetime import date, timedelta, timezone, datetime

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_job_po(company_id: int, suffix: str) -> str:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"Dispatch Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Dispatch Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-DISPATCH-{suffix}",
            status="ISSUED",
        )
        db.add(po)
        db.commit()
        return str(po.job_purchase_order_id)
    finally:
        db.close()


def _seed_employee(company_id: int, name: str) -> int:
    db = SessionLocal()
    try:
        emp = Employee(company_id=company_id, name=name, is_active=True, hourly_rate_cents=3000)
        db.add(emp)
        db.commit()
        return int(emp.id)
    finally:
        db.close()


def _create_ticket(company_id: int, suffix: str, service_type: str = "DROP") -> tuple[str, str, str]:
    site = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": f"Dispatch Builder {suffix}",
            "site_name": "Site",
            "address_line_1": f"{suffix} Dispatch St",
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T1T1T1",
        },
    )
    assert site.status_code == 200, site.text
    site_id = site.json()["customer_site_id"]

    po_id = _seed_job_po(company_id=company_id, suffix=suffix)

    req = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": "DROP",
            "request_notes": "dispatch",
        },
    )
    assert req.status_code == 200, req.text

    ticket = client.post(
        "/waste-bin/service-tickets",
        headers=_auth_headers(company_id),
        json={
            "bin_service_request_id": req.json()["bin_service_request_id"],
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "service_type": service_type,
            "status": "OPEN",
        },
    )
    assert ticket.status_code == 200, ticket.text
    return str(ticket.json()["bin_service_ticket_id"]), str(site_id), str(po_id)


def _create_bin_asset(company_id: int, site_id: str, po_id: str, suffix: str) -> str:
    asset = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(company_id),
        json={
            "bin_number": f"DISP-BIN-{suffix}",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
            "current_customer_site_id": site_id,
            "current_job_purchase_order_id": po_id,
        },
    )
    assert asset.status_code == 200, asset.text
    return str(asset.json()["bin_asset_id"])


def test_schedule_ticket_succeeds():
    company_id = 9961
    ticket_id, _site_id, _po_id = _create_ticket(company_id=company_id, suffix="A")

    schedule = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/schedule",
        headers=_auth_headers(company_id),
        json={
            "scheduled_date": date.today().isoformat(),
            "scheduled_time_window": "08:00-10:00",
            "priority": "HIGH",
        },
    )
    assert schedule.status_code == 200, schedule.text
    row = schedule.json()
    assert row["status"] == "SCHEDULED"
    assert row["priority"] == "HIGH"
    assert row["scheduled_time_window"] == "08:00-10:00"


def test_dispatch_ticket_succeeds():
    company_id = 9962
    ticket_id, _site_id, _po_id = _create_ticket(company_id=company_id, suffix="B")

    schedule = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/schedule",
        headers=_auth_headers(company_id),
        json={"scheduled_date": date.today().isoformat(), "priority": "NORMAL"},
    )
    assert schedule.status_code == 200, schedule.text

    dispatch = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/dispatch",
        headers=_auth_headers(company_id),
        json={},
    )
    assert dispatch.status_code == 200, dispatch.text
    row = dispatch.json()
    assert row["status"] == "DISPATCHED"
    assert row["dispatched_at"] is not None


def test_invalid_transitions_fail_with_409():
    company_id = 9963
    ticket_id, _site_id, _po_id = _create_ticket(company_id=company_id, suffix="C")

    cancel = client.patch(
        f"/waste-bin/service-tickets/{ticket_id}/assignment",
        headers=_auth_headers(company_id),
        json={"assigned_vehicle_label": "Truck-1"},
    )
    assert cancel.status_code == 200, cancel.text

    dispatch = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/dispatch",
        headers=_auth_headers(company_id),
        json={},
    )
    assert dispatch.status_code == 200, dispatch.text

    schedule_after_dispatch = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/schedule",
        headers=_auth_headers(company_id),
        json={"scheduled_date": date.today().isoformat(), "priority": "LOW"},
    )
    assert schedule_after_dispatch.status_code == 409, schedule_after_dispatch.text


def test_queue_filtering_works():
    company_id = 9964

    t1, site1, po1 = _create_ticket(company_id=company_id, suffix="D1")
    t2, site2, po2 = _create_ticket(company_id=company_id, suffix="D2")

    e1 = _seed_employee(company_id=company_id, name="Dispatch Emp")
    bin_id = _create_bin_asset(company_id=company_id, site_id=site1, po_id=po1, suffix="D1")

    s1 = client.post(
        f"/waste-bin/service-tickets/{t1}/schedule",
        headers=_auth_headers(company_id),
        json={"scheduled_date": date.today().isoformat(), "priority": "URGENT", "scheduled_time_window": "07:00-08:00"},
    )
    assert s1.status_code == 200, s1.text

    a1 = client.patch(
        f"/waste-bin/service-tickets/{t1}/assignment",
        headers=_auth_headers(company_id),
        json={
            "assigned_bin_asset_id": bin_id,
            "assigned_employee_id": e1,
            "assigned_vehicle_label": "Truck-42",
        },
    )
    assert a1.status_code == 200, a1.text

    s2 = client.post(
        f"/waste-bin/service-tickets/{t2}/schedule",
        headers=_auth_headers(company_id),
        json={"scheduled_date": (date.today() + timedelta(days=1)).isoformat(), "priority": "LOW"},
    )
    assert s2.status_code == 200, s2.text

    q = client.get(
        "/waste-bin/service-tickets/queue",
        headers=_auth_headers(company_id),
        params={
            "priority": "URGENT",
            "assigned_employee_id": e1,
            "job_purchase_order_id": po1,
            "customer_site_id": site1,
            "scheduled_date": date.today().isoformat(),
            "status": "SCHEDULED",
        },
    )
    assert q.status_code == 200, q.text
    rows = q.json()
    assert len(rows) == 1
    assert rows[0]["bin_service_ticket_id"] == t1


def test_today_view_ordering_works():
    company_id = 9965

    t1, _s1, _p1 = _create_ticket(company_id=company_id, suffix="E1")
    t2, _s2, _p2 = _create_ticket(company_id=company_id, suffix="E2")
    t3, _s3, _p3 = _create_ticket(company_id=company_id, suffix="E3")

    r1 = client.post(
        f"/waste-bin/service-tickets/{t1}/schedule",
        headers=_auth_headers(company_id),
        json={"scheduled_date": date.today().isoformat(), "priority": "HIGH", "scheduled_time_window": "10:00-12:00"},
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        f"/waste-bin/service-tickets/{t2}/schedule",
        headers=_auth_headers(company_id),
        json={"scheduled_date": date.today().isoformat(), "priority": "URGENT", "scheduled_time_window": "13:00-15:00"},
    )
    assert r2.status_code == 200, r2.text

    r3 = client.post(
        f"/waste-bin/service-tickets/{t3}/schedule",
        headers=_auth_headers(company_id),
        json={"scheduled_date": date.today().isoformat(), "priority": "HIGH", "scheduled_time_window": "08:00-09:00"},
    )
    assert r3.status_code == 200, r3.text

    today = client.get("/waste-bin/service-tickets/today", headers=_auth_headers(company_id))
    assert today.status_code == 200, today.text
    ids = [row["bin_service_ticket_id"] for row in today.json()]
    assert ids[0] == t2
    assert ids[1] == t3
    assert ids[2] == t1


def test_company_scoping_enforced_for_dispatch_endpoints():
    company_id = 9966
    other_company = 9967
    ticket_id, _site_id, _po_id = _create_ticket(company_id=company_id, suffix="F")

    schedule_other = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/schedule",
        headers=_auth_headers(other_company),
        json={"scheduled_date": date.today().isoformat(), "priority": "NORMAL"},
    )
    assert schedule_other.status_code == 404, schedule_other.text

    dispatch_other = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/dispatch",
        headers=_auth_headers(other_company),
        json={},
    )
    assert dispatch_other.status_code == 404, dispatch_other.text


def test_assignment_persists_bin_employee_vehicle():
    company_id = 9968
    ticket_id, site_id, po_id = _create_ticket(company_id=company_id, suffix="G")

    employee_id = _seed_employee(company_id=company_id, name="Driver G")
    bin_asset_id = _create_bin_asset(company_id=company_id, site_id=site_id, po_id=po_id, suffix="G")

    patch = client.patch(
        f"/waste-bin/service-tickets/{ticket_id}/assignment",
        headers=_auth_headers(company_id),
        json={
            "assigned_bin_asset_id": bin_asset_id,
            "assigned_employee_id": employee_id,
            "assigned_vehicle_label": "Truck-G",
        },
    )
    assert patch.status_code == 200, patch.text
    row = patch.json()
    assert row["assigned_bin_asset_id"] == bin_asset_id
    assert row["assigned_employee_id"] == employee_id
    assert row["assigned_vehicle_label"] == "Truck-G"

from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.bin_route_run import BinRouteRun
from app.models.bin_route_run_stop import BinRouteRunStop
from app.models.employee import Employee
from app.models.job import Job
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "route-run-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _seed_job_po(company_id: int, suffix: str) -> str:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"Route Job {suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Route Scope {suffix}")
        db.add(scope)
        db.flush()

        po = JobPurchaseOrder(
            company_id=company_id,
            job_id=job.id,
            scope_id=scope.id,
            po_number=f"PO-ROUTE-{suffix}",
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
        row = Employee(company_id=company_id, name=name, is_active=True, hourly_rate_cents=3000)
        db.add(row)
        db.commit()
        return int(row.id)
    finally:
        db.close()


def _create_ticket(company_id: int, suffix: str, *, scheduled_date: str, status: str = "SCHEDULED") -> tuple[str, str, str]:
    site = client.post(
        "/waste-bin/customer-sites",
        headers=_auth_headers(company_id),
        json={
            "customer_name": f"Route Builder {suffix}",
            "site_name": "Route Site",
            "address_line_1": f"{suffix} Route Street",
            "city": "Edmonton",
            "province": "AB",
            "postal_code": "T1T1T1",
        },
    )
    assert site.status_code == 200, site.text
    site_id = str(site.json()["customer_site_id"])

    po_id = _seed_job_po(company_id=company_id, suffix=suffix)

    req = client.post(
        "/waste-bin/service-requests",
        headers=_auth_headers(company_id),
        json={
            "customer_site_id": site_id,
            "job_purchase_order_id": po_id,
            "request_type": "DROP",
            "request_notes": "route test",
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
            "service_type": "DROP",
            "status": "OPEN",
        },
    )
    assert ticket.status_code == 200, ticket.text
    ticket_id = str(ticket.json()["bin_service_ticket_id"])

    schedule = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/schedule",
        headers=_auth_headers(company_id),
        json={"scheduled_date": scheduled_date, "priority": "NORMAL", "scheduled_time_window": "08:00-10:00"},
    )
    assert schedule.status_code == 200, schedule.text

    if status == "DISPATCHED":
        dispatch = client.post(
            f"/waste-bin/service-tickets/{ticket_id}/dispatch",
            headers=_auth_headers(company_id),
            json={},
        )
        assert dispatch.status_code == 200, dispatch.text

    return ticket_id, site_id, po_id


def _create_asset(company_id: int, site_id: str, po_id: str, suffix: str) -> str:
    asset = client.post(
        "/waste-bin/assets",
        headers=_auth_headers(company_id),
        json={
            "bin_number": f"ROUTE-BIN-{suffix}",
            "bin_type": "ROLL_OFF",
            "bin_size": "20YD",
            "status": "AVAILABLE",
            "current_customer_site_id": site_id,
            "current_job_purchase_order_id": po_id,
        },
    )
    assert asset.status_code == 200, asset.text
    return str(asset.json()["bin_asset_id"])


def _add_ticket_photo(company_id: int, ticket_id: str, photo_type: str, key_suffix: str):
    response = client.post(
        f"/waste-bin/service-tickets/{ticket_id}/photos",
        headers=_auth_headers(company_id),
        json={
            "photo_type": photo_type,
            "storage_key": f"placeholder://{key_suffix}",
            "captured_at": "2026-03-10T12:00:00Z",
            "captured_lat": 53.5461,
            "captured_lng": -113.4938,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_route_run(company_id: int, suffix: str, *, route_status: str = "PLANNED") -> tuple[str, str, str]:
    driver_id = _seed_employee(company_id=company_id, name=f"Driver {suffix}")
    ticket_1, site_1, po_1 = _create_ticket(company_id=company_id, suffix=f"{suffix}A", scheduled_date=date.today().isoformat())
    ticket_2, site_2, po_2 = _create_ticket(
        company_id=company_id,
        suffix=f"{suffix}B",
        scheduled_date=date.today().isoformat(),
        status="DISPATCHED",
    )
    asset_1 = _create_asset(company_id=company_id, site_id=site_1, po_id=po_1, suffix=f"{suffix}A")
    asset_2 = _create_asset(company_id=company_id, site_id=site_2, po_id=po_2, suffix=f"{suffix}B")

    client.patch(
        f"/waste-bin/service-tickets/{ticket_1}/assignment",
        headers=_auth_headers(company_id),
        json={"assigned_bin_asset_id": asset_1, "assigned_employee_id": driver_id, "assigned_vehicle_label": "Truck-1"},
    )
    client.patch(
        f"/waste-bin/service-tickets/{ticket_2}/assignment",
        headers=_auth_headers(company_id),
        json={"assigned_bin_asset_id": asset_2, "assigned_employee_id": driver_id, "assigned_vehicle_label": "Truck-1"},
    )

    db = SessionLocal()
    try:
        route = BinRouteRun(
            company_id=company_id,
            route_label=f"North Route {suffix}",
            scheduled_date=date.today(),
            status=route_status,
            assigned_employee_id=driver_id,
            notes="AM route",
        )
        db.add(route)
        db.flush()

        db.add_all(
            [
                BinRouteRunStop(
                    company_id=company_id,
                    route_run_id=str(route.route_run_id),
                    bin_service_ticket_id=ticket_1,
                    sequence_index=1,
                    bin_asset_id=asset_1,
                ),
                BinRouteRunStop(
                    company_id=company_id,
                    route_run_id=str(route.route_run_id),
                    bin_service_ticket_id=ticket_2,
                    sequence_index=2,
                    bin_asset_id=asset_2,
                ),
            ]
        )
        db.commit()
        return str(route.route_run_id), ticket_1, ticket_2
    finally:
        db.close()


def _create_route_run_via_api(
    company_id: int,
    *,
    route_label: str,
    scheduled_date: str,
    assigned_employee_id: int | None = None,
    notes: str | None = None,
):
    response = client.post(
        "/waste-bin/routes",
        headers=_auth_headers(company_id),
        json={
            "route_label": route_label,
            "scheduled_date": scheduled_date,
            "assigned_employee_id": assigned_employee_id,
            "notes": notes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_route_stop_id(company_id: int, route_run_id: str, ticket_id: str) -> int:
    detail = client.get(f"/waste-bin/routes/{route_run_id}", headers=_auth_headers(company_id))
    assert detail.status_code == 200, detail.text
    for stop in detail.json()["stops"]:
        if stop["ticket"]["bin_service_ticket_id"] == ticket_id:
            return int(stop["id"])
    raise AssertionError(f"stop not found for ticket {ticket_id}")


def test_route_run_read_shape_and_linked_ticket_retrieval():
    company_id = 55001
    route_run_id, ticket_1, ticket_2 = _seed_route_run(company_id, "A")

    listing = client.get("/waste-bin/routes", headers=_auth_headers(company_id))
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["route_run_id"] == route_run_id
    assert rows[0]["route_label"] == "North Route A"
    assert rows[0]["stop_count"] == 2
    assert rows[0]["assigned_bin_count"] == 2
    assert rows[0]["dispatched_ticket_count"] == 1

    detail = client.get(f"/waste-bin/routes/{route_run_id}", headers=_auth_headers(company_id))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["route_run_id"] == route_run_id
    assert body["stop_count"] == 2
    assert body["linked_bin_asset_ids"] != []
    assert body["stops"][0]["stop_status"] == "SCHEDULED"
    assert body["stops"][0]["is_dispatched"] is False
    assert body["stops"][0]["is_completed"] is False
    assert body["stops"][0]["is_skipped"] is False
    assert body["stops"][0]["ticket"]["dispatched_at"] is None
    assert body["stops"][0]["ticket"]["completed_at"] is None
    assert body["stops"][0]["ticket"]["completed_by_user_id"] is None
    assert body["stops"][0]["ticket"]["completion_notes"] is None
    assert [row["ticket"]["bin_service_ticket_id"] for row in body["stops"]] == [ticket_1, ticket_2]


def test_route_run_status_filtering_works():
    company_id = 55002
    _seed_route_run(company_id, "Planned", route_status="PLANNED")
    active_route_run_id, _, _ = _seed_route_run(company_id, "Active", route_status="ACTIVE")

    filtered = client.get(
        "/waste-bin/routes",
        headers=_auth_headers(company_id),
        params={"status": "ACTIVE", "scheduled_date": date.today().isoformat()},
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["route_run_id"] == active_route_run_id
    assert rows[0]["status"] == "ACTIVE"


def test_route_run_company_isolation_is_enforced():
    owner_company_id = 55003
    other_company_id = 55004
    route_run_id, _, _ = _seed_route_run(owner_company_id, "Scope")

    other_list = client.get("/waste-bin/routes", headers=_auth_headers(other_company_id))
    assert other_list.status_code == 200, other_list.text
    assert other_list.json() == []

    other_detail = client.get(f"/waste-bin/routes/{route_run_id}", headers=_auth_headers(other_company_id))
    assert other_detail.status_code == 404, other_detail.text


def test_invalid_route_run_id_returns_404():
    company_id = 55005

    detail = client.get("/waste-bin/routes/not-a-real-route-run", headers=_auth_headers(company_id))
    assert detail.status_code == 404, detail.text


def test_create_route_run_returns_created_record():
    company_id = 55006
    driver_id = _seed_employee(company_id=company_id, name="Create Driver")

    created = _create_route_run_via_api(
        company_id,
        route_label="South Loop",
        scheduled_date=date.today().isoformat(),
        assigned_employee_id=driver_id,
        notes="First shift",
    )

    assert created["route_label"] == "South Loop"
    assert created["scheduled_date"] == date.today().isoformat()
    assert created["status"] == "PLANNED"
    assert created["assigned_employee_id"] == driver_id
    assert created["notes"] == "First shift"
    assert created["stop_count"] == 0
    assert created["stops"] == []


def test_update_route_run_updates_editable_fields():
    company_id = 55007
    original_driver_id = _seed_employee(company_id=company_id, name="Original Driver")
    new_driver_id = _seed_employee(company_id=company_id, name="Replacement Driver")
    created = _create_route_run_via_api(
        company_id,
        route_label="West Route",
        scheduled_date=date.today().isoformat(),
        assigned_employee_id=original_driver_id,
        notes="AM",
    )

    updated = client.patch(
        f"/waste-bin/routes/{created['route_run_id']}",
        headers=_auth_headers(company_id),
        json={
            "route_label": "West Route PM",
            "assigned_employee_id": new_driver_id,
            "notes": "PM shift",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["route_label"] == "West Route PM"
    assert body["assigned_employee_id"] == new_driver_id
    assert body["notes"] == "PM shift"
    assert body["status"] == "PLANNED"


def test_assign_and_resequence_route_run_stops():
    company_id = 55008
    route_run_id, ticket_1, ticket_2 = _seed_route_run(company_id, "Resequence")

    resequence = client.put(
        f"/waste-bin/routes/{route_run_id}/stops",
        headers=_auth_headers(company_id),
        json={
            "stops": [
                {"service_ticket_id": ticket_2, "sequence_index": 1},
                {"service_ticket_id": ticket_1, "sequence_index": 2},
            ]
        },
    )
    assert resequence.status_code == 200, resequence.text
    body = resequence.json()
    assert [row["ticket"]["bin_service_ticket_id"] for row in body["stops"]] == [ticket_2, ticket_1]
    assert [row["sequence_index"] for row in body["stops"]] == [1, 2]


def test_dispatch_transition_moves_route_run_to_active():
    company_id = 55009
    created = _create_route_run_via_api(
        company_id,
        route_label="Dispatch Route",
        scheduled_date=date.today().isoformat(),
    )

    dispatch = client.post(
        f"/waste-bin/routes/{created['route_run_id']}/dispatch",
        headers=_auth_headers(company_id),
    )
    assert dispatch.status_code == 200, dispatch.text
    assert dispatch.json()["status"] == "ACTIVE"


def test_complete_transition_requires_completed_or_cancelled_tickets():
    company_id = 55010
    route_run_id, ticket_1, ticket_2 = _seed_route_run(company_id, "Complete")

    dispatch = client.post(f"/waste-bin/routes/{route_run_id}/dispatch", headers=_auth_headers(company_id))
    assert dispatch.status_code == 200, dispatch.text

    blocked = client.post(f"/waste-bin/routes/{route_run_id}/complete", headers=_auth_headers(company_id))
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"] == "Cannot complete route run while 2 stop(s) remain incomplete"

    _add_ticket_photo(company_id, ticket_1, "DROP_PROOF", "route-complete-1")
    _add_ticket_photo(company_id, ticket_2, "DROP_PROOF", "route-complete-2")

    complete_ticket_1 = client.post(
        f"/waste-bin/service-tickets/{ticket_1}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete_ticket_1.status_code == 200, complete_ticket_1.text

    complete_ticket_2 = client.post(
        f"/waste-bin/service-tickets/{ticket_2}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "done"},
    )
    assert complete_ticket_2.status_code == 200, complete_ticket_2.text

    completed = client.post(f"/waste-bin/routes/{route_run_id}/complete", headers=_auth_headers(company_id))
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "COMPLETED"


def test_cancel_transition_moves_route_run_to_cancelled():
    company_id = 55011
    created = _create_route_run_via_api(
        company_id,
        route_label="Cancel Route",
        scheduled_date=date.today().isoformat(),
    )

    cancelled = client.post(
        f"/waste-bin/routes/{created['route_run_id']}/cancel",
        headers=_auth_headers(company_id),
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"


def test_invalid_route_run_transitions_are_rejected():
    company_id = 55012
    created = _create_route_run_via_api(
        company_id,
        route_label="Invalid Transition Route",
        scheduled_date=date.today().isoformat(),
    )
    route_run_id = str(created["route_run_id"])

    complete_from_planned = client.post(f"/waste-bin/routes/{route_run_id}/complete", headers=_auth_headers(company_id))
    assert complete_from_planned.status_code == 409, complete_from_planned.text
    assert complete_from_planned.json()["detail"] == "Invalid route run status transition: PLANNED -> COMPLETED"

    dispatch = client.post(f"/waste-bin/routes/{route_run_id}/dispatch", headers=_auth_headers(company_id))
    assert dispatch.status_code == 200, dispatch.text

    cancel = client.post(f"/waste-bin/routes/{route_run_id}/cancel", headers=_auth_headers(company_id))
    assert cancel.status_code == 200, cancel.text

    dispatch_again = client.post(f"/waste-bin/routes/{route_run_id}/dispatch", headers=_auth_headers(company_id))
    assert dispatch_again.status_code == 409, dispatch_again.text
    assert dispatch_again.json()["detail"] == "Invalid route run status transition: CANCELLED -> ACTIVE"


def test_route_run_write_endpoints_enforce_company_isolation():
    owner_company_id = 55013
    other_company_id = 55014
    created = _create_route_run_via_api(
        owner_company_id,
        route_label="Scoped Route",
        scheduled_date=date.today().isoformat(),
    )
    owner_route_run_id = str(created["route_run_id"])
    other_ticket, _, _ = _create_ticket(other_company_id, "Other", scheduled_date=date.today().isoformat())

    patch_other = client.patch(
        f"/waste-bin/routes/{owner_route_run_id}",
        headers=_auth_headers(other_company_id),
        json={"notes": "intrusion"},
    )
    assert patch_other.status_code == 404, patch_other.text

    stops_other = client.put(
        f"/waste-bin/routes/{owner_route_run_id}/stops",
        headers=_auth_headers(other_company_id),
        json={"stops": [{"service_ticket_id": other_ticket, "sequence_index": 1}]},
    )
    assert stops_other.status_code == 404, stops_other.text

    dispatch_other = client.post(
        f"/waste-bin/routes/{owner_route_run_id}/dispatch",
        headers=_auth_headers(other_company_id),
    )
    assert dispatch_other.status_code == 404, dispatch_other.text


def test_dispatching_valid_stop_updates_stop_state_and_activates_route():
    company_id = 55015
    route_run_id, ticket_1, _ticket_2 = _seed_route_run(company_id, "StopDispatch")
    stop_id = _get_route_stop_id(company_id, route_run_id, ticket_1)

    dispatched = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/dispatch",
        headers=_auth_headers(company_id),
    )
    assert dispatched.status_code == 200, dispatched.text
    body = dispatched.json()
    assert body["status"] == "ACTIVE"
    first_stop = next(stop for stop in body["stops"] if stop["id"] == stop_id)
    assert first_stop["stop_status"] == "DISPATCHED"
    assert first_stop["is_dispatched"] is True
    assert first_stop["ticket"]["status"] == "DISPATCHED"


def test_completing_valid_stop_updates_stop_state():
    company_id = 55016
    route_run_id, ticket_1, _ticket_2 = _seed_route_run(company_id, "StopComplete")
    stop_id = _get_route_stop_id(company_id, route_run_id, ticket_1)

    _add_ticket_photo(company_id, ticket_1, "DROP_PROOF", "stop-complete-1")

    dispatch = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/dispatch",
        headers=_auth_headers(company_id),
    )
    assert dispatch.status_code == 200, dispatch.text

    completed = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "stop complete"},
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    stop = next(row for row in body["stops"] if row["id"] == stop_id)
    assert stop["stop_status"] == "COMPLETED"
    assert stop["is_completed"] is True
    assert stop["ticket"]["status"] == "COMPLETED"


def test_skipping_valid_stop_marks_ticket_cancelled():
    company_id = 55017
    route_run_id, ticket_1, _ticket_2 = _seed_route_run(company_id, "StopSkip")
    stop_id = _get_route_stop_id(company_id, route_run_id, ticket_1)

    dispatch = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/dispatch",
        headers=_auth_headers(company_id),
    )
    assert dispatch.status_code == 200, dispatch.text

    skipped = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/skip",
        headers=_auth_headers(company_id),
        json={"skip_reason": "site blocked"},
    )
    assert skipped.status_code == 200, skipped.text
    body = skipped.json()
    stop = next(row for row in body["stops"] if row["id"] == stop_id)
    assert stop["stop_status"] == "CANCELLED"
    assert stop["is_skipped"] is True
    assert stop["ticket"]["status"] == "CANCELLED"
    assert stop["ticket"]["completion_notes"] == "site blocked"


def test_invalid_stop_route_combination_returns_404():
    company_id = 55018
    route_run_id, ticket_1, _ticket_2 = _seed_route_run(company_id, "RouteA")
    other_route_run_id, other_ticket_1, _other_ticket_2 = _seed_route_run(company_id, "RouteB")
    stop_id = _get_route_stop_id(company_id, route_run_id, ticket_1)
    other_stop_id = _get_route_stop_id(company_id, other_route_run_id, other_ticket_1)

    mismatch = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{other_stop_id}/dispatch",
        headers=_auth_headers(company_id),
    )
    assert mismatch.status_code == 404, mismatch.text

    valid = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/dispatch",
        headers=_auth_headers(company_id),
    )
    assert valid.status_code == 200, valid.text


def test_invalid_stop_lifecycle_transitions_are_rejected():
    company_id = 55019
    route_run_id, ticket_1, _ticket_2 = _seed_route_run(company_id, "StopInvalid")
    stop_id = _get_route_stop_id(company_id, route_run_id, ticket_1)

    complete_while_planned = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "not allowed"},
    )
    assert complete_while_planned.status_code == 409, complete_while_planned.text
    assert complete_while_planned.json()["detail"] == "Cannot complete stop unless route run is ACTIVE"

    skip_while_planned = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/skip",
        headers=_auth_headers(company_id),
        json={"skip_reason": "blocked"},
    )
    assert skip_while_planned.status_code == 409, skip_while_planned.text
    assert skip_while_planned.json()["detail"] == "Cannot skip stop unless route run is ACTIVE"

    dispatch = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/dispatch",
        headers=_auth_headers(company_id),
    )
    assert dispatch.status_code == 200, dispatch.text

    skip = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/skip",
        headers=_auth_headers(company_id),
        json={"skip_reason": "blocked"},
    )
    assert skip.status_code == 200, skip.text

    dispatch_after_skip = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/dispatch",
        headers=_auth_headers(company_id),
    )
    assert dispatch_after_skip.status_code == 409, dispatch_after_skip.text
    assert dispatch_after_skip.json()["detail"] == "Cannot dispatch COMPLETED or CANCELLED ticket"


def test_stop_execution_endpoints_enforce_company_isolation():
    owner_company_id = 55020
    other_company_id = 55021
    route_run_id, ticket_1, _ticket_2 = _seed_route_run(owner_company_id, "StopScope")
    stop_id = _get_route_stop_id(owner_company_id, route_run_id, ticket_1)

    dispatch_other = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/dispatch",
        headers=_auth_headers(other_company_id),
    )
    assert dispatch_other.status_code == 404, dispatch_other.text

    complete_other = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/complete",
        headers=_auth_headers(other_company_id),
        json={"completion_notes": "nope"},
    )
    assert complete_other.status_code == 404, complete_other.text

    skip_other = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/skip",
        headers=_auth_headers(other_company_id),
        json={"skip_reason": "nope"},
    )
    assert skip_other.status_code == 404, skip_other.text


def test_route_completion_conflict_counts_remaining_incomplete_stops():
    company_id = 55022
    route_run_id, ticket_1, _ticket_2 = _seed_route_run(company_id, "CompletionGuard")
    stop_id = _get_route_stop_id(company_id, route_run_id, ticket_1)

    dispatch = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/dispatch",
        headers=_auth_headers(company_id),
    )
    assert dispatch.status_code == 200, dispatch.text

    _add_ticket_photo(company_id, ticket_1, "DROP_PROOF", "completion-guard-1")
    complete_first_stop = client.post(
        f"/waste-bin/routes/{route_run_id}/stops/{stop_id}/complete",
        headers=_auth_headers(company_id),
        json={"completion_notes": "first stop done"},
    )
    assert complete_first_stop.status_code == 200, complete_first_stop.text

    blocked = client.post(f"/waste-bin/routes/{route_run_id}/complete", headers=_auth_headers(company_id))
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"] == "Cannot complete route run while 1 stop(s) remain incomplete"

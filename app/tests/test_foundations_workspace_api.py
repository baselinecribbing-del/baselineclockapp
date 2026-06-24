from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.employee import Employee
from app.models.job import Job
from app.models.job_document import JobDocument
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "test-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_foundation_refs(company_id: int, name_suffix: str = "A") -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        employee = Employee(company_id=company_id, name=f"Emp {name_suffix}", is_active=True, hourly_rate_cents=3500)
        db.add(employee)
        db.flush()

        job = Job(company_id=company_id, name=f"Job {name_suffix}", is_active=True)
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Scope {name_suffix}", is_active=True)
        db.add(scope)
        db.commit()

        return int(employee.id), int(job.id), int(scope.id)
    finally:
        db.close()


def _seed_job_document(company_id: int, job_id: int, scope_id: int | None, name_suffix: str) -> str:
    db = SessionLocal()
    try:
        row = JobDocument(
            company_id=company_id,
            job_id=job_id,
            scope_id=scope_id,
            document_type="BLUEPRINT",
            file_name=f"foundation-{name_suffix}.pdf",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.job_document_id)
    finally:
        db.close()


def test_company_modules_create_list_and_company_scoping_and_unique_constraint():
    c1 = 8101
    c2 = 8102

    create = client.post(
        "/company-modules",
        headers=_auth_headers(c1),
        json={"module_code": "FOUNDATIONS", "is_enabled": True},
    )
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["company_id"] == c1
    assert created["module_code"] == "FOUNDATIONS"

    duplicate = client.post(
        "/company-modules",
        headers=_auth_headers(c1),
        json={"module_code": "FOUNDATIONS", "is_enabled": False},
    )
    assert duplicate.status_code == 409, duplicate.text

    invalid_module = client.post(
        "/company-modules",
        headers=_auth_headers(c1),
        json={"module_code": "PAYROLL"},
    )
    assert invalid_module.status_code == 422

    c1_list = client.get("/company-modules", headers=_auth_headers(c1))
    assert c1_list.status_code == 200, c1_list.text
    assert len(c1_list.json()) == 1

    c2_list = client.get("/company-modules", headers=_auth_headers(c2))
    assert c2_list.status_code == 200, c2_list.text
    assert c2_list.json() == []


def test_crew_assignments_create_list_filters_and_status_validation():
    company_id = 8201
    employee_id, job_id, scope_id = _seed_foundation_refs(company_id, "Crew")

    create = client.post(
        "/foundations/crew-assignments",
        headers=_auth_headers(company_id, user_id="foreman-a"),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "assigned_date": date(2026, 3, 7).isoformat(),
            "assignment_notes": "Footing crew assigned",
            "status": "ASSIGNED",
        },
    )
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["employee_id"] == employee_id
    assert created["job_id"] == job_id
    assert created["scope_id"] == scope_id
    assert created["status"] == "ASSIGNED"
    assert created["assigned_by_user_id"] == "foreman-a"
    assert created["acknowledged_at"] is None
    assert created["acknowledged_by_employee_id"] is None

    filtered = client.get(
        "/foundations/crew-assignments",
        headers=_auth_headers(company_id),
        params={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "assigned_date": date(2026, 3, 7).isoformat(),
            "status": "ASSIGNED",
        },
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["crew_assignment_id"] == created["crew_assignment_id"]

    invalid_status = client.post(
        "/foundations/crew-assignments",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "assigned_date": date(2026, 3, 7).isoformat(),
            "status": "DONE",
        },
    )
    assert invalid_status.status_code == 422


def test_hazard_assessments_create_list_and_company_scoping():
    c1 = 8301
    c2 = 8302

    employee_id, job_id, scope_id = _seed_foundation_refs(c1, "Haz")

    create = client.post(
        "/foundations/hazard-assessments",
        headers=_auth_headers(c1),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "completed_by_employee_id": employee_id,
            "assessment_date": date(2026, 3, 7).isoformat(),
            "form_payload": {
                "weather": "clear",
                "risks": ["rebar", "excavation edge"],
                "controls": ["barricade", "ppe"],
            },
        },
    )
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["company_id"] == c1
    assert created["job_id"] == job_id

    filtered = client.get(
        "/foundations/hazard-assessments",
        headers=_auth_headers(c1),
        params={
            "job_id": job_id,
            "scope_id": scope_id,
            "completed_by_employee_id": employee_id,
            "assessment_date": date(2026, 3, 7).isoformat(),
        },
    )
    assert filtered.status_code == 200, filtered.text
    assert len(filtered.json()) == 1

    other_company = client.get("/foundations/hazard-assessments", headers=_auth_headers(c2))
    assert other_company.status_code == 200, other_company.text
    assert other_company.json() == []


def test_toolbox_meetings_create_list_and_company_scoping():
    c1 = 8401
    c2 = 8402

    employee_id, job_id, scope_id = _seed_foundation_refs(c1, "Tool")

    create = client.post(
        "/foundations/toolbox-meetings",
        headers=_auth_headers(c1),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "meeting_date": date(2026, 3, 7).isoformat(),
            "completed_by_employee_id": employee_id,
            "attendee_count": 6,
            "form_payload": {
                "topic": "Morning safety",
                "actions": ["review PPE", "review excavation plan"],
            },
        },
    )
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["company_id"] == c1
    assert created["attendee_count"] == 6

    filtered = client.get(
        "/foundations/toolbox-meetings",
        headers=_auth_headers(c1),
        params={
            "job_id": job_id,
            "scope_id": scope_id,
            "meeting_date": date(2026, 3, 7).isoformat(),
            "completed_by_employee_id": employee_id,
        },
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["toolbox_meeting_id"] == created["toolbox_meeting_id"]

    negative_attendees = client.post(
        "/foundations/toolbox-meetings",
        headers=_auth_headers(c1),
        json={
            "meeting_date": date(2026, 3, 7).isoformat(),
            "completed_by_employee_id": employee_id,
            "attendee_count": -1,
            "form_payload": {"topic": "invalid"},
        },
    )
    assert negative_attendees.status_code == 422

    other_company = client.get("/foundations/toolbox-meetings", headers=_auth_headers(c2))
    assert other_company.status_code == 200
    assert other_company.json() == []


def test_job_document_delivery_tracking_create_list_filters_and_scoping():
    c1 = 8501
    c2 = 8502

    employee_id, job_id, scope_id = _seed_foundation_refs(c1, "Doc")
    c2_employee_id, c2_job_id, c2_scope_id = _seed_foundation_refs(c2, "Doc2")

    doc_1 = _seed_job_document(c1, job_id, scope_id, "1")
    _seed_job_document(c2, c2_job_id, c2_scope_id, "2")

    deliver = client.post(
        f"/foundations/job-documents/{doc_1}/deliver",
        headers=_auth_headers(c1),
        json={"employee_id": employee_id},
    )
    assert deliver.status_code == 200, deliver.text
    delivered = deliver.json()
    assert delivered["company_id"] == c1
    assert delivered["job_document_id"] == doc_1
    assert delivered["employee_id"] == employee_id
    assert delivered["viewed_at"] is None

    list_by_employee = client.get(
        "/foundations/job-documents/deliveries",
        headers=_auth_headers(c1),
        params={"employee_id": employee_id},
    )
    assert list_by_employee.status_code == 200, list_by_employee.text
    assert len(list_by_employee.json()) == 1

    list_by_document = client.get(
        "/foundations/job-documents/deliveries",
        headers=_auth_headers(c1),
        params={"job_document_id": doc_1, "job_id": job_id},
    )
    assert list_by_document.status_code == 200, list_by_document.text
    assert len(list_by_document.json()) == 1

    not_found_cross_company = client.post(
        f"/foundations/job-documents/{doc_1}/deliver",
        headers=_auth_headers(c2),
        json={"employee_id": c2_employee_id},
    )
    assert not_found_cross_company.status_code == 404

    c2_list = client.get("/foundations/job-documents/deliveries", headers=_auth_headers(c2))
    assert c2_list.status_code == 200
    assert c2_list.json() == []


def test_crew_assignment_acknowledge_success_double_ack_fails_and_company_scoping():
    c1 = 8601
    c2 = 8602
    employee_id, job_id, _scope_id = _seed_foundation_refs(c1, "Ack")
    c2_employee_id, _c2_job_id, _c2_scope_id = _seed_foundation_refs(c2, "Ack2")

    create = client.post(
        "/foundations/crew-assignments",
        headers=_auth_headers(c1),
        json={
            "employee_id": employee_id,
            "job_id": job_id,
            "assigned_date": date(2026, 3, 8).isoformat(),
            "status": "ASSIGNED",
        },
    )
    assert create.status_code == 200, create.text
    assignment_id = create.json()["crew_assignment_id"]

    ack = client.post(
        f"/foundations/crew-assignments/{assignment_id}/acknowledge",
        headers=_auth_headers(c1),
        json={"acknowledged_by_employee_id": employee_id},
    )
    assert ack.status_code == 200, ack.text
    ack_body = ack.json()
    assert ack_body["status"] == "ACKNOWLEDGED"
    assert ack_body["acknowledged_by_employee_id"] == employee_id
    assert ack_body["acknowledged_at"] is not None

    double_ack = client.post(
        f"/foundations/crew-assignments/{assignment_id}/acknowledge",
        headers=_auth_headers(c1),
        json={"acknowledged_by_employee_id": employee_id},
    )
    assert double_ack.status_code == 409, double_ack.text

    cross_company = client.post(
        f"/foundations/crew-assignments/{assignment_id}/acknowledge",
        headers=_auth_headers(c2),
        json={"acknowledged_by_employee_id": c2_employee_id},
    )
    assert cross_company.status_code == 404


def test_foundations_messages_create_list_filter_and_scoping():
    c1 = 8701
    c2 = 8702
    employee_id, job_id, scope_id = _seed_foundation_refs(c1, "Msg")
    _c2_employee_id, c2_job_id, c2_scope_id = _seed_foundation_refs(c2, "Msg2")

    create_1 = client.post(
        "/foundations/messages",
        headers=_auth_headers(c1, user_id="site-super"),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "employee_id": employee_id,
            "message_type": "JOB_INSTRUCTION",
            "subject": "Footing sequence",
            "body": "Start on west edge then move south.",
        },
    )
    assert create_1.status_code == 200, create_1.text
    row_1 = create_1.json()
    assert row_1["company_id"] == c1
    assert row_1["created_by_user_id"] == "site-super"
    assert row_1["message_type"] == "JOB_INSTRUCTION"

    create_2 = client.post(
        "/foundations/messages",
        headers=_auth_headers(c1),
        json={
            "message_type": "BROADCAST",
            "body": "Concrete truck delay 30 mins.",
        },
    )
    assert create_2.status_code == 200, create_2.text

    filtered = client.get(
        "/foundations/messages",
        headers=_auth_headers(c1),
        params={
            "employee_id": employee_id,
            "job_id": job_id,
            "scope_id": scope_id,
            "message_type": "JOB_INSTRUCTION",
        },
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["foundations_message_id"] == row_1["foundations_message_id"]

    other_company_isolated = client.post(
        "/foundations/messages",
        headers=_auth_headers(c2),
        json={
            "job_id": c2_job_id,
            "scope_id": c2_scope_id,
            "message_type": "SAFETY_NOTICE",
            "body": "Use fall protection near excavation.",
        },
    )
    assert other_company_isolated.status_code == 200, other_company_isolated.text

    c1_list = client.get("/foundations/messages", headers=_auth_headers(c1))
    assert c1_list.status_code == 200
    assert len(c1_list.json()) == 2

    c2_list = client.get("/foundations/messages", headers=_auth_headers(c2))
    assert c2_list.status_code == 200
    assert len(c2_list.json()) == 1


def test_job_document_delivery_mark_viewed_once_and_filtering():
    company_id = 8801
    employee_id, job_id, scope_id = _seed_foundation_refs(company_id, "View")
    doc_id = _seed_job_document(company_id, job_id, scope_id, "view")

    delivered = client.post(
        f"/foundations/job-documents/{doc_id}/deliver",
        headers=_auth_headers(company_id),
        json={"employee_id": employee_id},
    )
    assert delivered.status_code == 200, delivered.text
    delivery_id = delivered.json()["job_document_delivery_id"]
    assert delivered.json()["viewed_at"] is None

    mark = client.post(
        f"/foundations/job-documents/deliveries/{delivery_id}/mark-viewed",
        headers=_auth_headers(company_id),
    )
    assert mark.status_code == 200, mark.text
    assert mark.json()["viewed_at"] is not None

    mark_again = client.post(
        f"/foundations/job-documents/deliveries/{delivery_id}/mark-viewed",
        headers=_auth_headers(company_id),
    )
    assert mark_again.status_code == 409, mark_again.text

    viewed_only = client.get(
        "/foundations/job-documents/deliveries",
        headers=_auth_headers(company_id),
        params={"viewed": "true"},
    )
    assert viewed_only.status_code == 200, viewed_only.text
    assert len(viewed_only.json()) == 1

    unviewed_only = client.get(
        "/foundations/job-documents/deliveries",
        headers=_auth_headers(company_id),
        params={"viewed": "false"},
    )
    assert unviewed_only.status_code == 200, unviewed_only.text
    assert unviewed_only.json() == []


def test_foundations_compliance_review_endpoints_filter_and_scope():
    c1 = 8901
    c2 = 8902
    employee_id, job_id, scope_id = _seed_foundation_refs(c1, "Comp")
    c2_employee_id, c2_job_id, c2_scope_id = _seed_foundation_refs(c2, "Comp2")

    h_create = client.post(
        "/foundations/hazard-assessments",
        headers=_auth_headers(c1),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "completed_by_employee_id": employee_id,
            "assessment_date": date(2026, 3, 5).isoformat(),
            "form_payload": {"hazard": "rebar ends"},
        },
    )
    assert h_create.status_code == 200, h_create.text

    t_create = client.post(
        "/foundations/toolbox-meetings",
        headers=_auth_headers(c1),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "meeting_date": date(2026, 3, 6).isoformat(),
            "completed_by_employee_id": employee_id,
            "attendee_count": 8,
            "form_payload": {"topic": "pour prep"},
        },
    )
    assert t_create.status_code == 200, t_create.text

    c2_h_create = client.post(
        "/foundations/hazard-assessments",
        headers=_auth_headers(c2),
        json={
            "job_id": c2_job_id,
            "scope_id": c2_scope_id,
            "completed_by_employee_id": c2_employee_id,
            "assessment_date": date(2026, 3, 5).isoformat(),
            "form_payload": {"hazard": "other"},
        },
    )
    assert c2_h_create.status_code == 200, c2_h_create.text

    hazards_review = client.get(
        "/foundations/compliance/hazard-assessments",
        headers=_auth_headers(c1),
        params={
            "job_id": job_id,
            "scope_id": scope_id,
            "completed_by_employee_id": employee_id,
            "date_from": date(2026, 3, 1).isoformat(),
            "date_to": date(2026, 3, 10).isoformat(),
        },
    )
    assert hazards_review.status_code == 200, hazards_review.text
    assert len(hazards_review.json()) == 1

    toolbox_review = client.get(
        "/foundations/compliance/toolbox-meetings",
        headers=_auth_headers(c1),
        params={
            "job_id": job_id,
            "scope_id": scope_id,
            "completed_by_employee_id": employee_id,
            "date_from": date(2026, 3, 1).isoformat(),
            "date_to": date(2026, 3, 10).isoformat(),
        },
    )
    assert toolbox_review.status_code == 200, toolbox_review.text
    assert len(toolbox_review.json()) == 1

    c2_hazards_review = client.get(
        "/foundations/compliance/hazard-assessments",
        headers=_auth_headers(c2),
    )
    assert c2_hazards_review.status_code == 200
    assert len(c2_hazards_review.json()) == 1

from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.job import Job
from app.models.scope import Scope
from app.services.po_parser import extract_po_details

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test-user", "company_id": company_id})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _seed_job_scope(company_id: int, name_suffix: str) -> tuple[int, int]:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"PO Job {name_suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"PO Scope {name_suffix}")
        db.add(scope)
        db.commit()
        return int(job.id), int(scope.id)
    finally:
        db.close()


def test_create_and_list_email_ingestion_events_with_parse_status_filter_and_company_scoping():
    c1 = 7101
    c2 = 7102

    create_1 = client.post(
        "/job-documents/email-ingestion-events",
        headers=_auth_headers(c1),
        json={
            "source_message_id": "msg-001",
            "sender_email": "vendor1@example.com",
            "subject": "PO 2026-004 for JOB 13",
            "parse_status": "PARSED",
            "parsed_po_number": "2026-004",
            "parsed_job_id": 13,
        },
    )
    assert create_1.status_code == 200, create_1.text
    row_1 = create_1.json()
    assert row_1["company_id"] == c1
    assert row_1["parse_status"] == "PARSED"

    create_2 = client.post(
        "/job-documents/email-ingestion-events",
        headers=_auth_headers(c1),
        json={
            "source_message_id": "msg-002",
            "sender_email": "vendor2@example.com",
            "subject": "Missing PO info",
            "parse_status": "FAILED",
            "parse_notes": "No PO number found",
        },
    )
    assert create_2.status_code == 200, create_2.text

    list_all = client.get("/job-documents/email-ingestion-events", headers=_auth_headers(c1))
    assert list_all.status_code == 200, list_all.text
    all_rows = list_all.json()
    assert len(all_rows) == 2

    list_parsed = client.get(
        "/job-documents/email-ingestion-events",
        headers=_auth_headers(c1),
        params={"parse_status": "PARSED"},
    )
    assert list_parsed.status_code == 200, list_parsed.text
    parsed_rows = list_parsed.json()
    assert len(parsed_rows) == 1
    assert parsed_rows[0]["source_message_id"] == "msg-001"

    list_other_company = client.get("/job-documents/email-ingestion-events", headers=_auth_headers(c2))
    assert list_other_company.status_code == 200, list_other_company.text
    assert list_other_company.json() == []


def test_create_and_list_purchase_orders_with_unique_company_po_enforced():
    company_id = 7201
    other_company = 7202

    job_id, scope_id = _seed_job_scope(company_id=company_id, name_suffix="A")
    other_job_id, _ = _seed_job_scope(company_id=other_company, name_suffix="B")

    create = client.post(
        "/job-documents/purchase-orders",
        headers=_auth_headers(company_id),
        json={
            "job_id": job_id,
            "scope_id": scope_id,
            "po_number": "PO-ABCD-1001",
            "vendor_name": "Steel Supplier",
            "vendor_email": "ap@steel.example.com",
            "status": "ISSUED",
            "issued_date": date(2026, 3, 1).isoformat(),
        },
    )
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["company_id"] == company_id
    assert created["po_number"] == "PO-ABCD-1001"
    assert created["job_id"] == job_id

    listing = client.get(
        "/job-documents/purchase-orders",
        headers=_auth_headers(company_id),
        params={"job_id": job_id, "scope_id": scope_id, "po_number": "PO-ABCD-1001"},
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["job_purchase_order_id"] == created["job_purchase_order_id"]

    duplicate = client.post(
        "/job-documents/purchase-orders",
        headers=_auth_headers(company_id),
        json={
            "job_id": job_id,
            "po_number": "PO-ABCD-1001",
            "status": "DRAFT",
        },
    )
    assert duplicate.status_code == 409, duplicate.text

    other_company_same_po = client.post(
        "/job-documents/purchase-orders",
        headers=_auth_headers(other_company),
        json={
            "job_id": other_job_id,
            "po_number": "PO-ABCD-1001",
            "status": "DRAFT",
        },
    )
    assert other_company_same_po.status_code == 200, other_company_same_po.text

    c1_view = client.get("/job-documents/purchase-orders", headers=_auth_headers(company_id))
    assert c1_view.status_code == 200
    assert len(c1_view.json()) == 1

    c2_view = client.get("/job-documents/purchase-orders", headers=_auth_headers(other_company))
    assert c2_view.status_code == 200
    assert len(c2_view.json()) == 1


def test_po_parser_extracts_po_number_and_job_reference_from_subject_and_text():
    parsed = extract_po_details(
        subject="Re: Purchase Order #PO-7788 for project updates",
        text="Please process JOB REF J-4421 this week.",
    )
    assert parsed.po_number == "PO-7788"
    assert parsed.job_reference == "J-4421"

    parsed_from_body = extract_po_details(
        subject="Weekly update",
        text="Attached docs for PO number 900-XYZ and Job #55-ALPHA",
    )
    assert parsed_from_body.po_number == "900-XYZ"
    assert parsed_from_body.job_reference == "55-ALPHA"

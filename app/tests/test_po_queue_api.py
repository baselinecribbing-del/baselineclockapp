from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.customer_site import CustomerSite
from app.models.job import Job
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


def _seed_job_scope(company_id: int, name_suffix: str) -> tuple[int, int]:
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name=f"PO Queue Job {name_suffix}")
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"PO Queue Scope {name_suffix}")
        db.add(scope)
        db.commit()
        return int(job.id), int(scope.id)
    finally:
        db.close()


def _seed_customer_site(company_id: int, name_suffix: str) -> str:
    db = SessionLocal()
    try:
        site = CustomerSite(
            company_id=company_id,
            customer_name=f"Customer {name_suffix}",
            site_name=f"Site {name_suffix}",
            address_line_1=f"{name_suffix} Main St",
            city="Calgary",
            province="AB",
            postal_code="T2P1J9",
        )
        db.add(site)
        db.commit()
        db.refresh(site)
        return str(site.customer_site_id)
    finally:
        db.close()


def _create_po(*, company_id: int, job_id: int, scope_id: int | None, po_number: str) -> dict:
    body = {
        "job_id": job_id,
        "po_number": po_number,
        "status": "ISSUED",
    }
    if scope_id is not None:
        body["scope_id"] = scope_id

    resp = client.post("/job-documents/purchase-orders", headers=_auth_headers(company_id), json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_po_queue_listing_filtering_and_ordering_with_company_scoping():
    c1 = 9101
    c2 = 9102

    c1_job, c1_scope = _seed_job_scope(company_id=c1, name_suffix="A")
    c2_job, c2_scope = _seed_job_scope(company_id=c2, name_suffix="B")
    c1_site = _seed_customer_site(company_id=c1, name_suffix="A")

    po_1 = _create_po(company_id=c1, job_id=c1_job, scope_id=c1_scope, po_number="PO-QUEUE-001")
    po_2 = _create_po(company_id=c1, job_id=c1_job, scope_id=c1_scope, po_number="PO-QUEUE-002")
    _create_po(company_id=c2, job_id=c2_job, scope_id=c2_scope, po_number="PO-QUEUE-003")

    matched = client.post(
        f"/job-documents/purchase-orders/{po_1['job_purchase_order_id']}/match",
        headers=_auth_headers(c1, user_id="queue-reviewer"),
        json={
            "matched_job_id": c1_job,
            "matched_scope_id": c1_scope,
            "matched_customer_site_id": c1_site,
            "review_notes": "matched in queue",
        },
    )
    assert matched.status_code == 200, matched.text

    list_all = client.get("/job-documents/purchase-orders/queue", headers=_auth_headers(c1))
    assert list_all.status_code == 200, list_all.text
    rows = list_all.json()
    assert [row["job_purchase_order_id"] for row in rows] == [
        po_2["job_purchase_order_id"],
        po_1["job_purchase_order_id"],
    ]

    by_status = client.get(
        "/job-documents/purchase-orders/queue",
        headers=_auth_headers(c1),
        params={"queue_status": "MATCHED"},
    )
    assert by_status.status_code == 200, by_status.text
    by_status_rows = by_status.json()
    assert len(by_status_rows) == 1
    assert by_status_rows[0]["job_purchase_order_id"] == po_1["job_purchase_order_id"]

    by_po_number = client.get(
        "/job-documents/purchase-orders/queue",
        headers=_auth_headers(c1),
        params={"po_number": "PO-QUEUE-002"},
    )
    assert by_po_number.status_code == 200, by_po_number.text
    by_po_rows = by_po_number.json()
    assert len(by_po_rows) == 1
    assert by_po_rows[0]["job_purchase_order_id"] == po_2["job_purchase_order_id"]

    by_linkage = client.get(
        "/job-documents/purchase-orders/queue",
        headers=_auth_headers(c1),
        params={
            "matched_job_id": c1_job,
            "matched_scope_id": c1_scope,
            "matched_customer_site_id": c1_site,
        },
    )
    assert by_linkage.status_code == 200, by_linkage.text
    by_linkage_rows = by_linkage.json()
    assert len(by_linkage_rows) == 1
    assert by_linkage_rows[0]["job_purchase_order_id"] == po_1["job_purchase_order_id"]

    c2_queue = client.get("/job-documents/purchase-orders/queue", headers=_auth_headers(c2))
    assert c2_queue.status_code == 200, c2_queue.text
    c2_rows = c2_queue.json()
    assert len(c2_rows) == 1
    assert c2_rows[0]["po_number"] == "PO-QUEUE-003"


def test_match_po_to_job_scope_site_persists_linkage_and_review_metadata():
    company_id = 9201
    job_id, scope_id = _seed_job_scope(company_id=company_id, name_suffix="C")
    site_id = _seed_customer_site(company_id=company_id, name_suffix="C")
    po = _create_po(company_id=company_id, job_id=job_id, scope_id=scope_id, po_number="PO-MATCH-100")

    resp = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/match",
        headers=_auth_headers(company_id, user_id="reviewer-100"),
        json={
            "matched_job_id": job_id,
            "matched_scope_id": scope_id,
            "matched_customer_site_id": site_id,
            "review_notes": "verified",
        },
    )
    assert resp.status_code == 200, resp.text

    row = resp.json()
    assert row["queue_status"] == "MATCHED"
    assert row["matched_job_id"] == job_id
    assert row["matched_scope_id"] == scope_id
    assert row["matched_customer_site_id"] == site_id
    assert row["reviewed_by_user_id"] == "reviewer-100"
    assert row["reviewed_at"] is not None
    assert row["review_notes"] == "verified"


def test_mark_ready_for_ops_succeeds_when_minimum_linkage_exists():
    company_id = 9301
    job_id, scope_id = _seed_job_scope(company_id=company_id, name_suffix="D")
    site_id = _seed_customer_site(company_id=company_id, name_suffix="D")
    po = _create_po(company_id=company_id, job_id=job_id, scope_id=scope_id, po_number="PO-READY-100")

    matched = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/match",
        headers=_auth_headers(company_id, user_id="reviewer-match"),
        json={
            "matched_job_id": job_id,
            "matched_scope_id": scope_id,
            "matched_customer_site_id": site_id,
        },
    )
    assert matched.status_code == 200, matched.text

    ready = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(company_id, user_id="reviewer-ready"),
        json={"review_notes": "ready for ops"},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["queue_status"] == "READY_FOR_OPS"


def test_mark_ready_for_ops_fails_when_linkage_missing():
    company_id = 9401
    job_id, scope_id = _seed_job_scope(company_id=company_id, name_suffix="E")
    po = _create_po(company_id=company_id, job_id=job_id, scope_id=scope_id, po_number="PO-READY-FAIL")

    ready = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(company_id),
        json={},
    )
    assert ready.status_code == 409, ready.text
    assert "without matched job and customer site linkage" in ready.json()["detail"]


def test_close_po_queue_item_succeeds():
    company_id = 9501
    job_id, scope_id = _seed_job_scope(company_id=company_id, name_suffix="F")
    po = _create_po(company_id=company_id, job_id=job_id, scope_id=scope_id, po_number="PO-CLOSE-100")

    closed = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/close",
        headers=_auth_headers(company_id, user_id="reviewer-close"),
        json={"review_notes": "closed by reviewer"},
    )
    assert closed.status_code == 200, closed.text

    row = closed.json()
    assert row["queue_status"] == "CLOSED"
    assert row["reviewed_by_user_id"] == "reviewer-close"
    assert row["reviewed_at"] is not None


def test_po_queue_invalid_transitions_fail_with_409():
    company_id = 9601
    job_id, scope_id = _seed_job_scope(company_id=company_id, name_suffix="G")
    site_id = _seed_customer_site(company_id=company_id, name_suffix="G")
    po = _create_po(company_id=company_id, job_id=job_id, scope_id=scope_id, po_number="PO-TRANS-100")

    matched = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/match",
        headers=_auth_headers(company_id),
        json={
            "matched_job_id": job_id,
            "matched_scope_id": scope_id,
            "matched_customer_site_id": site_id,
        },
    )
    assert matched.status_code == 200, matched.text

    ready = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(company_id),
        json={},
    )
    assert ready.status_code == 200, ready.text

    rematch = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/match",
        headers=_auth_headers(company_id),
        json={
            "matched_job_id": job_id,
            "matched_scope_id": scope_id,
            "matched_customer_site_id": site_id,
        },
    )
    assert rematch.status_code == 409, rematch.text

    closed = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/close",
        headers=_auth_headers(company_id),
        json={},
    )
    assert closed.status_code == 200, closed.text

    reclose = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/close",
        headers=_auth_headers(company_id),
        json={},
    )
    assert reclose.status_code == 409, reclose.text


def test_po_queue_company_scoping_enforced_for_actions():
    c1 = 9701
    c2 = 9702

    c1_job, c1_scope = _seed_job_scope(company_id=c1, name_suffix="H")
    c2_job, c2_scope = _seed_job_scope(company_id=c2, name_suffix="I")
    c2_site = _seed_customer_site(company_id=c2, name_suffix="I")

    po = _create_po(company_id=c1, job_id=c1_job, scope_id=c1_scope, po_number="PO-SCOPE-100")

    match_other_company = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/match",
        headers=_auth_headers(c2),
        json={
            "matched_job_id": c2_job,
            "matched_scope_id": c2_scope,
            "matched_customer_site_id": c2_site,
        },
    )
    assert match_other_company.status_code == 404, match_other_company.text

    ready_other_company = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/ready",
        headers=_auth_headers(c2),
        json={},
    )
    assert ready_other_company.status_code == 404, ready_other_company.text

    close_other_company = client.post(
        f"/job-documents/purchase-orders/{po['job_purchase_order_id']}/close",
        headers=_auth_headers(c2),
        json={},
    )
    assert close_other_company.status_code == 404, close_other_company.text

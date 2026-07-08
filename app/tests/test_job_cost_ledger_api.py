from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.database import SessionLocal
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.scope import Scope

client = TestClient(app)


def _auth_headers(company_id: int) -> dict:
    resp = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert isinstance(data, dict), f"token response not a JSON object: {data}"
    assert "access_token" in data, f"token response missing access_token: {data}"
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {data['access_token']}"}


def _insert_row(company_id: int, job_id: int, source_reference_id: str):
    db = SessionLocal()
    try:
        row = JobCostLedger(
            company_id=company_id,
            job_id=job_id,
            scope_id=None,
            employee_id=None,
            source_type="LABOR",
            source_reference_id=source_reference_id,
            cost_category="LABOR_GROSS",
            job_purchase_order_id=None,
            cost_source="PAYROLL",
            quantity=None,
            unit_cost_cents=None,
            total_cost_cents=123,
            posting_date=datetime.utcnow(),
            immutable_flag=True,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _seed_po(*, company_id: int, job_id: int, po_id: str, po_number: str, scope_id: int | None = None) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.company_id == company_id, Job.id == job_id).one_or_none()
        if job is None:
            db.add(Job(id=job_id, company_id=company_id, name=f"Seeded Job {job_id}"))
            db.flush()
        db.execute(
            text(
                """
                INSERT INTO job_purchase_orders
                    (job_purchase_order_id, company_id, job_id, scope_id, po_number, status, queue_status)
                VALUES
                    (:job_purchase_order_id, :company_id, :job_id, :scope_id, :po_number, 'ISSUED', 'RECEIVED')
                """
            ),
            {
                "job_purchase_order_id": po_id,
                "company_id": company_id,
                "job_id": job_id,
                "scope_id": scope_id,
                "po_number": po_number,
            },
        )
        db.commit()
    finally:
        db.close()


def test_ledger_read_filters_by_company():
    ref1 = f"c1-{uuid4()}"
    ref2 = f"c2-{uuid4()}"
    company_1 = 7001
    company_2 = 7002
    job_id = 7101

    _insert_row(company_id=company_1, job_id=job_id, source_reference_id=ref1)
    _insert_row(company_id=company_2, job_id=job_id, source_reference_id=ref2)

    r1 = client.get(f"/costing/job/{job_id}/ledger", headers=_auth_headers(company_1))
    assert r1.status_code == 200
    data1 = r1.json()
    refs1 = [row["source_reference_id"] for row in data1["rows"]]
    assert ref1 in refs1
    assert ref2 not in refs1

    r2 = client.get(f"/costing/job/{job_id}/ledger", headers=_auth_headers(company_2))
    assert r2.status_code == 200
    data2 = r2.json()
    refs2 = [row["source_reference_id"] for row in data2["rows"]]
    assert ref2 in refs2
    assert ref1 not in refs2


def test_costing_requires_company_header():
    r = client.get("/costing/job/1/ledger")
    assert r.status_code == 401


def test_job_ledger_includes_traceability_fields_and_supports_filters():
    company_id = 7003
    job_id = 7103
    po_id = f"po-{uuid4()}"
    _seed_po(company_id=company_id, job_id=job_id, po_id=po_id, po_number="PO-LEDGER-1")

    db = SessionLocal()
    try:
        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id=f"po:{po_id}:Concrete",
                    cost_category="material",
                    job_purchase_order_id=po_id,
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=datetime.utcnow(),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id=f"landfill:{uuid4()}:dump",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=12000,
                    total_cost_cents=12000,
                    posting_date=datetime.utcnow(),
                    immutable_flag=True,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    res = client.get(f"/costing/job/{job_id}/ledger", headers=_auth_headers(company_id))
    assert res.status_code == 200, res.text
    rows = res.json()["rows"]
    assert len(rows) >= 2

    by_source = {row["cost_source"]: row for row in rows if row["cost_source"] in {"PO", "MANUAL"}}
    assert by_source["PO"]["job_purchase_order_id"] == po_id
    assert by_source["PO"]["source_reference_id"] == f"po:{po_id}:Concrete"
    assert by_source["MANUAL"]["job_purchase_order_id"] is None

    po_only = client.get(
        f"/costing/job/{job_id}/ledger",
        headers=_auth_headers(company_id),
        params={"cost_source": "PO", "job_purchase_order_id": po_id},
    )
    assert po_only.status_code == 200, po_only.text
    po_rows = po_only.json()["rows"]
    assert len(po_rows) == 1
    assert po_rows[0]["cost_source"] == "PO"
    assert po_rows[0]["job_purchase_order_id"] == po_id


def test_job_cost_summary_groups_mixed_sources_for_job():
    company_id = 7004
    job_id = 7104
    po_id = f"po-{uuid4()}"
    _seed_po(company_id=company_id, job_id=job_id, po_id=po_id, po_number="PO-SUMMARY-1")

    db = SessionLocal()
    try:
        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=88,
                    source_type="payroll_run_labor",
                    source_reference_id="pr:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="8",
                    unit_cost_cents=3000,
                    total_cost_cents=24000,
                    posting_date=datetime(2026, 3, 1, 12, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id=f"po:{po_id}:Steel",
                    cost_category="material",
                    job_purchase_order_id=po_id,
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=datetime(2026, 3, 2, 12, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:sum:1",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=12000,
                    total_cost_cents=12000,
                    posting_date=datetime(2026, 3, 3, 12, 0, 0),
                    immutable_flag=True,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    res = client.get(
        f"/costing/job/{job_id}/summary",
        headers=_auth_headers(company_id),
        params={
            "date_start": "2026-03-01T00:00:00",
            "date_end": "2026-03-03T00:00:00",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["job_id"] == job_id
    assert body["row_count"] == 2
    assert body["total_cost_cents"] == 74000
    assert body["groups"] == [
        {
            "cost_category": "labor",
            "cost_source": "PAYROLL",
            "row_count": 1,
            "total_cost_cents": 24000,
        },
        {
            "cost_category": "material",
            "cost_source": "PO",
            "row_count": 1,
            "total_cost_cents": 50000,
        },
    ]


def test_job_cost_daily_summary_groups_by_day_for_job():
    company_id = 7005
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name="Daily Summary API Job")
        db.add(job)
        db.flush()
        scope = Scope(company_id=company_id, job_id=int(job.id), name="Daily Summary API Scope")
        db.add(scope)
        db.flush()
        other_scope = Scope(company_id=company_id, job_id=int(job.id), name="Daily Summary API Other Scope")
        db.add(other_scope)
        db.flush()
        po_id = "po-daily-1"
        db.execute(
            text(
                """
                INSERT INTO job_purchase_orders
                    (job_purchase_order_id, company_id, job_id, scope_id, po_number, status, queue_status)
                VALUES
                    (:job_purchase_order_id, :company_id, :job_id, :scope_id, :po_number, 'ISSUED', 'RECEIVED')
                """
            ),
            {
                "job_purchase_order_id": po_id,
                "company_id": company_id,
                "job_id": int(job.id),
                "scope_id": int(scope.id),
                "po_number": "PO-DAILY-API-1",
            },
        )

        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=88,
                    source_type="payroll_run_labor",
                    source_reference_id="pr:daily:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="4",
                    unit_cost_cents=3000,
                    total_cost_cents=12000,
                    posting_date=datetime(2026, 3, 5, 8, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=89,
                    source_type="payroll_run_labor",
                    source_reference_id="pr:daily:2",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="4",
                    unit_cost_cents=3000,
                    total_cost_cents=12000,
                    posting_date=datetime(2026, 3, 5, 12, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id="po:daily:steel",
                    cost_category="material",
                    job_purchase_order_id=po_id,
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=datetime(2026, 3, 6, 9, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(other_scope.id),
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:daily:excluded-scope",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=9000,
                    total_cost_cents=9000,
                    posting_date=datetime(2026, 3, 6, 14, 0, 0),
                    immutable_flag=True,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    res = client.get(
        f"/costing/job/{int(job.id)}/summary/daily",
        headers=_auth_headers(company_id),
        params={
            "scope_id": int(scope.id),
            "date_start": "2026-03-05T00:00:00",
            "date_end": "2026-03-07T00:00:00",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["job_id"] == int(job.id)
    assert body["scope_id"] == int(scope.id)
    assert body["row_count"] == 3
    assert body["total_cost_cents"] == 74000
    assert body["groups"] == [
        {
            "posting_date": "2026-03-05",
            "cost_category": "labor",
            "cost_source": "PAYROLL",
            "row_count": 2,
            "total_cost_cents": 24000,
        },
        {
            "posting_date": "2026-03-06",
            "cost_category": "material",
            "cost_source": "PO",
            "row_count": 1,
            "total_cost_cents": 50000,
        },
    ]


def test_job_cost_source_reference_summary_filters_to_summary_bucket():
    company_id = 7006
    job_id = 7106
    po_id = f"po-{uuid4()}"
    _seed_po(company_id=company_id, job_id=job_id, po_id=po_id, po_number="PO-SOURCE-1")

    db = SessionLocal()
    try:
        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=88,
                    source_type="payroll_run_labor",
                    source_reference_id="pr:source:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="8",
                    unit_cost_cents=3000,
                    total_cost_cents=24000,
                    posting_date=datetime(2026, 5, 1, 9, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=89,
                    source_type="payroll_run_labor",
                    source_reference_id="pr:source:2",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="4",
                    unit_cost_cents=3000,
                    total_cost_cents=12000,
                    posting_date=datetime(2026, 5, 1, 10, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id=f"po:{po_id}:Steel",
                    cost_category="material",
                    job_purchase_order_id=po_id,
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=datetime(2026, 5, 2, 12, 0, 0),
                    immutable_flag=True,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    summary = client.get(
        f"/costing/job/{job_id}/summary",
        headers=_auth_headers(company_id),
        params={
            "date_start": "2026-05-01T00:00:00",
            "date_end": "2026-05-03T00:00:00",
        },
    )
    assert summary.status_code == 200, summary.text
    labor_group = next(group for group in summary.json()["groups"] if group["cost_category"] == "labor")

    res = client.get(
        f"/costing/job/{job_id}/summary/sources",
        headers=_auth_headers(company_id),
        params={
            "date_start": "2026-05-01T00:00:00",
            "date_end": "2026-05-03T00:00:00",
            "cost_category": "labor",
            "cost_source": "PAYROLL",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["filters"] == {
        "cost_category": "labor",
        "cost_source": "PAYROLL",
        "source_type": None,
        "job_purchase_order_id": None,
    }
    assert body["row_count"] == labor_group["row_count"] == 2
    assert body["total_cost_cents"] == labor_group["total_cost_cents"] == 36000
    assert body["groups"] == [
        {
            "source_type": "payroll_run_labor",
            "source_reference_id": "pr:source:1",
            "cost_category": "labor",
            "cost_source": "PAYROLL",
            "job_purchase_order_id": None,
            "row_count": 1,
            "total_cost_cents": 24000,
        },
        {
            "source_type": "payroll_run_labor",
            "source_reference_id": "pr:source:2",
            "cost_category": "labor",
            "cost_source": "PAYROLL",
            "job_purchase_order_id": None,
            "row_count": 1,
            "total_cost_cents": 12000,
        },
    ]


def test_costing_read_models_reconcile_for_same_scope_and_date_window():
    company_id = 7007
    db = SessionLocal()
    try:
        job = Job(company_id=company_id, name="Cross Endpoint Reconciliation Job")
        db.add(job)
        db.flush()
        scope = Scope(company_id=company_id, job_id=int(job.id), name="Reconciliation Scope")
        db.add(scope)
        db.flush()
        other_scope = Scope(company_id=company_id, job_id=int(job.id), name="Excluded Scope")
        db.add(other_scope)
        db.flush()
        po_id = "po-reconcile-1"
        db.execute(
            text(
                """
                INSERT INTO job_purchase_orders
                    (job_purchase_order_id, company_id, job_id, scope_id, po_number, status, queue_status)
                VALUES
                    (:job_purchase_order_id, :company_id, :job_id, :scope_id, :po_number, 'ISSUED', 'RECEIVED')
                """
            ),
            {
                "job_purchase_order_id": po_id,
                "company_id": company_id,
                "job_id": int(job.id),
                "scope_id": int(scope.id),
                "po_number": "PO-RECON-1",
            },
        )

        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=88,
                    source_type="payroll_run_labor",
                    source_reference_id="pr:reconcile:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="8",
                    unit_cost_cents=3000,
                    total_cost_cents=24000,
                    posting_date=datetime(2026, 6, 1, 9, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=89,
                    source_type="payroll_run_labor",
                    source_reference_id="pr:reconcile:2",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="4",
                    unit_cost_cents=3000,
                    total_cost_cents=12000,
                    posting_date=datetime(2026, 6, 1, 12, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id=f"po:{po_id}:Steel",
                    cost_category="material",
                    job_purchase_order_id=po_id,
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=datetime(2026, 6, 2, 10, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:reconcile:1",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=12000,
                    total_cost_cents=12000,
                    posting_date=datetime(2026, 6, 3, 11, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:reconcile:out-of-range",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=9000,
                    total_cost_cents=9000,
                    posting_date=datetime(2026, 6, 4, 11, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(other_scope.id),
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:excluded:scope",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=70000,
                    total_cost_cents=70000,
                    posting_date=datetime(2026, 6, 2, 15, 0, 0),
                    immutable_flag=True,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    params = {
        "scope_id": int(scope.id),
        "date_start": "2026-06-01T00:00:00",
        "date_end": "2026-06-04T00:00:00",
    }

    ledger = client.get(
        f"/costing/job/{int(job.id)}/ledger",
        headers=_auth_headers(company_id),
        params=params,
    )
    assert ledger.status_code == 200, ledger.text
    ledger_body = ledger.json()
    ledger_row_count = len(ledger_body["rows"])
    ledger_total_cost = sum(row["total_cost_cents"] for row in ledger_body["rows"])
    assert ledger_row_count == 4
    assert ledger_total_cost == 98000

    summary = client.get(
        f"/costing/job/{int(job.id)}/summary",
        headers=_auth_headers(company_id),
        params=params,
    )
    assert summary.status_code == 200, summary.text
    summary_body = summary.json()
    assert summary_body["row_count"] == ledger_row_count
    assert summary_body["total_cost_cents"] == ledger_total_cost

    daily = client.get(
        f"/costing/job/{int(job.id)}/summary/daily",
        headers=_auth_headers(company_id),
        params=params,
    )
    assert daily.status_code == 200, daily.text
    daily_body = daily.json()
    assert daily_body["row_count"] == ledger_row_count
    assert daily_body["total_cost_cents"] == ledger_total_cost

    sources = client.get(
        f"/costing/job/{int(job.id)}/summary/sources",
        headers=_auth_headers(company_id),
        params=params,
    )
    assert sources.status_code == 200, sources.text
    sources_body = sources.json()
    assert sources_body["row_count"] == ledger_row_count
    assert sources_body["total_cost_cents"] == ledger_total_cost

    totals = client.get(
        "/costing/ledger/totals",
        headers=_auth_headers(company_id),
        params={**params, "job_id": int(job.id)},
    )
    assert totals.status_code == 200, totals.text
    totals_body = totals.json()
    totals_row_count = sum(group["row_count"] for group in totals_body["groups"])
    totals_total_cost = sum(group["total_cost_cents"] for group in totals_body["groups"])
    assert totals_row_count == ledger_row_count
    assert totals_total_cost == ledger_total_cost

    summary_bucket_totals = {
        (group["cost_category"], group["cost_source"]): (group["row_count"], group["total_cost_cents"])
        for group in summary_body["groups"]
    }
    source_bucket_totals: dict[tuple[str, str], tuple[int, int]] = {}
    for group in sources_body["groups"]:
        key = (group["cost_category"], group["cost_source"])
        prev_rows, prev_total = source_bucket_totals.get(key, (0, 0))
        source_bucket_totals[key] = (
            prev_rows + group["row_count"],
            prev_total + group["total_cost_cents"],
        )
    assert source_bucket_totals == summary_bucket_totals


def test_job_cost_source_type_summary_supports_mixed_source_analysis():
    company_id = 7008
    job_id = 7108
    po_id = f"po-{uuid4()}"
    _seed_po(company_id=company_id, job_id=job_id, po_id=po_id, po_number="PO-SOURCE-TYPE-1")

    db = SessionLocal()
    try:
        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=88,
                    source_type="payroll_run_labor",
                    source_reference_id="pr:stype:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="8",
                    unit_cost_cents=3000,
                    total_cost_cents=24000,
                    posting_date=datetime(2026, 7, 1, 9, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=89,
                    source_type="payroll_adjustment",
                    source_reference_id="adj:stype:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="1",
                    unit_cost_cents=6000,
                    total_cost_cents=6000,
                    posting_date=datetime(2026, 7, 1, 11, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id=f"po:{po_id}:Concrete",
                    cost_category="material",
                    job_purchase_order_id=po_id,
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=datetime(2026, 7, 2, 10, 0, 0),
                    immutable_flag=True,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=job_id,
                    scope_id=None,
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:stype:1",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=12000,
                    total_cost_cents=12000,
                    posting_date=datetime(2026, 7, 3, 10, 0, 0),
                    immutable_flag=True,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    summary = client.get(
        f"/costing/job/{job_id}/summary",
        headers=_auth_headers(company_id),
        params={
            "date_start": "2026-07-01T00:00:00",
            "date_end": "2026-07-04T00:00:00",
        },
    )
    assert summary.status_code == 200, summary.text
    summary_body = summary.json()

    res = client.get(
        f"/costing/job/{job_id}/summary/source-types",
        headers=_auth_headers(company_id),
        params={
            "date_start": "2026-07-01T00:00:00",
            "date_end": "2026-07-04T00:00:00",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["row_count"] == summary_body["row_count"] == 4
    assert body["total_cost_cents"] == summary_body["total_cost_cents"] == 92000
    assert body["groups"] == [
        {
            "source_type": "landfill_trip",
            "cost_category": "dump_cost",
            "cost_source": "MANUAL",
            "row_count": 1,
            "total_cost_cents": 12000,
        },
        {
            "source_type": "payroll_adjustment",
            "cost_category": "labor",
            "cost_source": "PAYROLL",
            "row_count": 1,
            "total_cost_cents": 6000,
        },
        {
            "source_type": "payroll_run_labor",
            "cost_category": "labor",
            "cost_source": "PAYROLL",
            "row_count": 1,
            "total_cost_cents": 24000,
        },
        {
            "source_type": "purchase_order_cost",
            "cost_category": "material",
            "cost_source": "PO",
            "row_count": 1,
            "total_cost_cents": 50000,
        },
    ]

    source_type_rollup: dict[tuple[str, str], tuple[int, int]] = {}
    for group in body["groups"]:
        key = (group["cost_category"], group["cost_source"])
        prev_rows, prev_total = source_type_rollup.get(key, (0, 0))
        source_type_rollup[key] = (
            prev_rows + group["row_count"],
            prev_total + group["total_cost_cents"],
        )
    assert source_type_rollup == {
        (group["cost_category"], group["cost_source"]): (group["row_count"], group["total_cost_cents"])
        for group in summary_body["groups"]
    }


def test_costing_read_endpoints_reject_impossible_po_filter_combinations():
    company_id = 7009
    job_id = 7109
    po_id = f"po-{uuid4()}"
    _seed_po(company_id=company_id, job_id=job_id, po_id=po_id, po_number="PO-INVALID-FILTER-1")
    headers = _auth_headers(company_id)
    expected_detail = "job_purchase_order_id is only valid when cost_source is omitted or 'PO'"

    ledger = client.get(
        f"/costing/job/{job_id}/ledger",
        headers=headers,
        params={"job_purchase_order_id": po_id, "cost_source": "MANUAL"},
    )
    assert ledger.status_code == 400, ledger.text
    assert ledger.json()["detail"] == expected_detail

    sources = client.get(
        f"/costing/job/{job_id}/summary/sources",
        headers=headers,
        params={"job_purchase_order_id": po_id, "cost_source": "PAYROLL"},
    )
    assert sources.status_code == 400, sources.text
    assert sources.json()["detail"] == expected_detail

    source_types = client.get(
        f"/costing/job/{job_id}/summary/source-types",
        headers=headers,
        params={"job_purchase_order_id": po_id, "cost_source": "MANUAL"},
    )
    assert source_types.status_code == 400, source_types.text
    assert source_types.json()["detail"] == expected_detail

    totals = client.get(
        "/costing/ledger/totals",
        headers=headers,
        params={
            "date_start": "2026-08-01T00:00:00",
            "date_end": "2026-08-02T00:00:00",
            "job_purchase_order_id": po_id,
            "cost_source": "PAYROLL",
        },
    )
    assert totals.status_code == 400, totals.text
    assert totals.json()["detail"] == expected_detail

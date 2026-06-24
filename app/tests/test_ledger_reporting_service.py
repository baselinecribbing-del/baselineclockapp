from datetime import datetime, timezone

from sqlalchemy import text

from app.database import SessionLocal
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.scope import Scope
from app.services.ledger_reporting_service import (
    job_cost_daily_summary_by_category_source,
    job_cost_summary_by_source_type,
    job_cost_summary_by_source_reference,
    job_cost_summary_by_category_source,
    job_cost_totals,
)


def _seed_po(db, *, company_id: int, job_id: int, scope_id: int | None, po_id: str, po_number: str) -> None:
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


def test_job_cost_totals_groups_and_sums():
    db = SessionLocal()
    try:
        company_id = 1
        d1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        d2 = datetime(2026, 1, 3, tzinfo=timezone.utc)
        d3 = datetime(2026, 1, 4, tzinfo=timezone.utc)

        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=10,
                    scope_id=None,
                    employee_id=100,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-x:1",
                    cost_category="labor",
                    quantity="8",
                    unit_cost_cents=3000,
                    total_cost_cents=24000,
                    posting_date=d1,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=10,
                    scope_id=None,
                    employee_id=100,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-x:2",
                    cost_category="labor",
                    quantity="2",
                    unit_cost_cents=3000,
                    total_cost_cents=6000,
                    posting_date=d2,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=11,
                    scope_id=None,
                    employee_id=101,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-x:3",
                    cost_category="labor",
                    quantity="5",
                    unit_cost_cents=3200,
                    total_cost_cents=16000,
                    posting_date=d2,
                ),
            ]
        )
        db.commit()

        res = job_cost_totals(
            company_id=company_id,
            date_start=d1,
            date_end=d3,
            db=db,
        )

        groups = res["groups"]
        assert len(groups) == 2

        g0 = groups[0]
        g1 = groups[1]

        assert (g0["job_id"], g0["employee_id"]) == (10, 100)
        assert g0["row_count"] == 2
        assert g0["total_cost_cents"] == 30000

        assert (g1["job_id"], g1["employee_id"]) == (11, 101)
        assert g1["row_count"] == 1
        assert g1["total_cost_cents"] == 16000

    finally:
        db.close()


def test_job_cost_totals_supports_cost_traceability_filters():
    db = SessionLocal()
    try:
        company_id = 2
        d1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
        d2 = datetime(2026, 2, 2, tzinfo=timezone.utc)
        po_id = "po-trace-1"

        job = Job(company_id=company_id, name="Traceability Job")
        db.add(job)
        db.flush()
        _seed_po(
            db,
            company_id=company_id,
            job_id=int(job.id),
            scope_id=None,
            po_id=po_id,
            po_number="PO-TRACE-1",
        )

        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
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
                    posting_date=d1,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill-trip-1:dump",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=12000,
                    total_cost_cents=12000,
                    posting_date=d1,
                ),
            ]
        )
        db.commit()

        res = job_cost_totals(
            company_id=company_id,
            date_start=d1,
            date_end=d2,
            db=db,
            cost_source="PO",
            job_purchase_order_id=po_id,
        )

        assert res["filters"]["cost_source"] == "PO"
        assert res["filters"]["job_purchase_order_id"] == po_id
        assert len(res["groups"]) == 1
        assert res["groups"][0]["job_id"] == int(job.id)
        assert res["groups"][0]["row_count"] == 1
        assert res["groups"][0]["total_cost_cents"] == 50000
    finally:
        db.close()


def test_job_cost_summary_groups_by_category_and_source():
    db = SessionLocal()
    try:
        company_id = 3
        d1 = datetime(2026, 3, 1, tzinfo=timezone.utc)
        d2 = datetime(2026, 3, 2, tzinfo=timezone.utc)
        d3 = datetime(2026, 3, 3, tzinfo=timezone.utc)
        job = Job(company_id=company_id, name="Summary Job")
        db.add(job)
        db.flush()
        _seed_po(
            db,
            company_id=company_id,
            job_id=int(job.id),
            scope_id=None,
            po_id="abc",
            po_number="PO-SUM-1",
        )

        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=100,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-sum:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="8",
                    unit_cost_cents=3000,
                    total_cost_cents=24000,
                    posting_date=d1,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id="po:abc:Concrete",
                    cost_category="material",
                    job_purchase_order_id="abc",
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=d2,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:1:dump",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=12000,
                    total_cost_cents=12000,
                    posting_date=d2,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:1:km",
                    cost_category="equipment",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="10",
                    unit_cost_cents=200,
                    total_cost_cents=2000,
                    posting_date=d3,
                ),
            ]
        )
        db.commit()

        res = job_cost_summary_by_category_source(
            company_id=company_id,
            job_id=int(job.id),
            date_start=d1,
            date_end=d3,
            db=db,
        )

        assert res["job_id"] == int(job.id)
        assert res["row_count"] == 3
        assert res["total_cost_cents"] == 86000
        assert res["date_start"] == d1.isoformat()
        assert res["date_end"] == d3.isoformat()
        assert res["groups"] == [
            {
                "cost_category": "dump_cost",
                "cost_source": "MANUAL",
                "row_count": 1,
                "total_cost_cents": 12000,
            },
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
    finally:
        db.close()


def test_job_cost_daily_summary_groups_by_posting_date_category_and_source():
    db = SessionLocal()
    try:
        company_id = 4
        d1 = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
        d1_late = datetime(2026, 4, 1, 17, 0, tzinfo=timezone.utc)
        d2 = datetime(2026, 4, 2, 9, 0, tzinfo=timezone.utc)
        d3 = datetime(2026, 4, 3, 9, 0, tzinfo=timezone.utc)
        job = Job(company_id=company_id, name="Daily Summary Job")
        db.add(job)
        db.flush()
        scope = Scope(company_id=company_id, job_id=int(job.id), name="Daily Summary Scope")
        db.add(scope)
        db.flush()
        other_scope = Scope(company_id=company_id, job_id=int(job.id), name="Other Daily Summary Scope")
        db.add(other_scope)
        db.flush()
        _seed_po(
            db,
            company_id=company_id,
            job_id=int(job.id),
            scope_id=int(scope.id),
            po_id="po-daily",
            po_number="PO-DAILY-1",
        )

        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=100,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-daily:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="4",
                    unit_cost_cents=3000,
                    total_cost_cents=12000,
                    posting_date=d1,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=101,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-daily:2",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="4",
                    unit_cost_cents=3000,
                    total_cost_cents=12000,
                    posting_date=d1_late,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id="po:daily:steel",
                    cost_category="material",
                    job_purchase_order_id="po-daily",
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=d2,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(other_scope.id),
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:daily:skip",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=9000,
                    total_cost_cents=9000,
                    posting_date=d2,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=int(scope.id),
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:daily:outside-range",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=11000,
                    total_cost_cents=11000,
                    posting_date=d3,
                ),
            ]
        )
        db.commit()

        res = job_cost_daily_summary_by_category_source(
            company_id=company_id,
            job_id=int(job.id),
            scope_id=int(scope.id),
            date_start=d1,
            date_end=d3,
            db=db,
        )

        assert res["job_id"] == int(job.id)
        assert res["scope_id"] == int(scope.id)
        assert res["row_count"] == 3
        assert res["total_cost_cents"] == 74000
        assert res["groups"] == [
            {
                "posting_date": "2026-04-01",
                "cost_category": "labor",
                "cost_source": "PAYROLL",
                "row_count": 2,
                "total_cost_cents": 24000,
            },
            {
                "posting_date": "2026-04-02",
                "cost_category": "material",
                "cost_source": "PO",
                "row_count": 1,
                "total_cost_cents": 50000,
            },
        ]
    finally:
        db.close()


def test_job_cost_source_reference_summary_drills_into_mixed_source_bucket():
    db = SessionLocal()
    try:
        company_id = 5
        d1 = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
        d2 = datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc)
        d3 = datetime(2026, 5, 3, 9, 0, tzinfo=timezone.utc)
        job = Job(company_id=company_id, name="Source Summary Job")
        db.add(job)
        db.flush()
        _seed_po(
            db,
            company_id=company_id,
            job_id=int(job.id),
            scope_id=None,
            po_id="po-source-1",
            po_number="PO-SOURCE-1",
        )

        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=100,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-src:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="8",
                    unit_cost_cents=3000,
                    total_cost_cents=24000,
                    posting_date=d1,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=101,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-src:2",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="4",
                    unit_cost_cents=3000,
                    total_cost_cents=12000,
                    posting_date=d1,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id="po:po-source-1:Concrete",
                    cost_category="material",
                    job_purchase_order_id="po-source-1",
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=d2,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=None,
                    source_type="landfill_trip",
                    source_reference_id="landfill:src:1",
                    cost_category="dump_cost",
                    job_purchase_order_id=None,
                    cost_source="MANUAL",
                    quantity="1",
                    unit_cost_cents=12000,
                    total_cost_cents=12000,
                    posting_date=d3,
                ),
            ]
        )
        db.commit()

        summary = job_cost_summary_by_category_source(
            company_id=company_id,
            job_id=int(job.id),
            date_start=d1,
            date_end=d3,
            db=db,
        )
        labor_group = next(group for group in summary["groups"] if group["cost_category"] == "labor")

        drilldown = job_cost_summary_by_source_reference(
            company_id=company_id,
            job_id=int(job.id),
            date_start=d1,
            date_end=d3,
            cost_category="labor",
            cost_source="PAYROLL",
            db=db,
        )

        assert drilldown["filters"]["cost_category"] == "labor"
        assert drilldown["filters"]["cost_source"] == "PAYROLL"
        assert drilldown["row_count"] == labor_group["row_count"] == 2
        assert drilldown["total_cost_cents"] == labor_group["total_cost_cents"] == 36000
        assert drilldown["groups"] == [
            {
                "source_type": "payroll_run_labor",
                "source_reference_id": "pr-src:1",
                "cost_category": "labor",
                "cost_source": "PAYROLL",
                "job_purchase_order_id": None,
                "row_count": 1,
                "total_cost_cents": 24000,
            },
            {
                "source_type": "payroll_run_labor",
                "source_reference_id": "pr-src:2",
                "cost_category": "labor",
                "cost_source": "PAYROLL",
                "job_purchase_order_id": None,
                "row_count": 1,
                "total_cost_cents": 12000,
            },
        ]
    finally:
        db.close()


def test_job_cost_source_type_summary_reconciles_to_summary_bucket_totals():
    db = SessionLocal()
    try:
        company_id = 6
        d1 = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
        d2 = datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc)
        job = Job(company_id=company_id, name="Source Type Summary Job")
        db.add(job)
        db.flush()
        _seed_po(
            db,
            company_id=company_id,
            job_id=int(job.id),
            scope_id=None,
            po_id="po-source-type-1",
            po_number="PO-SOURCE-TYPE-1",
        )

        db.add_all(
            [
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=100,
                    source_type="payroll_run_labor",
                    source_reference_id="pr-st:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="8",
                    unit_cost_cents=3000,
                    total_cost_cents=24000,
                    posting_date=d1,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=101,
                    source_type="payroll_adjustment",
                    source_reference_id="adj-st:1",
                    cost_category="labor",
                    job_purchase_order_id=None,
                    cost_source="PAYROLL",
                    quantity="1",
                    unit_cost_cents=6000,
                    total_cost_cents=6000,
                    posting_date=d1,
                ),
                JobCostLedger(
                    company_id=company_id,
                    job_id=int(job.id),
                    scope_id=None,
                    employee_id=None,
                    source_type="purchase_order_cost",
                    source_reference_id="po:po-source-type-1:Steel",
                    cost_category="material",
                    job_purchase_order_id="po-source-type-1",
                    cost_source="PO",
                    quantity=None,
                    unit_cost_cents=None,
                    total_cost_cents=50000,
                    posting_date=d2,
                ),
            ]
        )
        db.commit()

        summary = job_cost_summary_by_category_source(
            company_id=company_id,
            job_id=int(job.id),
            date_start=d1,
            date_end=datetime(2026, 6, 3, 0, 0, tzinfo=timezone.utc),
            db=db,
        )
        source_types = job_cost_summary_by_source_type(
            company_id=company_id,
            job_id=int(job.id),
            date_start=d1,
            date_end=datetime(2026, 6, 3, 0, 0, tzinfo=timezone.utc),
            db=db,
        )

        assert source_types["row_count"] == summary["row_count"] == 3
        assert source_types["total_cost_cents"] == summary["total_cost_cents"] == 80000
        assert source_types["groups"] == [
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

        bucket_rollup: dict[tuple[str, str], tuple[int, int]] = {}
        for group in source_types["groups"]:
            key = (group["cost_category"], group["cost_source"])
            prev_rows, prev_total = bucket_rollup.get(key, (0, 0))
            bucket_rollup[key] = (
                prev_rows + group["row_count"],
                prev_total + group["total_cost_cents"],
            )
        assert bucket_rollup == {
            (group["cost_category"], group["cost_source"]): (group["row_count"], group["total_cost_cents"])
            for group in summary["groups"]
        }
    finally:
        db.close()

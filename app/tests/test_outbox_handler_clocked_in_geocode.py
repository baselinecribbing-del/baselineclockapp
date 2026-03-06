from __future__ import annotations

import json
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.event_outbox import EventOutbox
from app.models.time_entry import TimeEntry
from app.services.outbox_handlers import handle_time_entry_clocked_in


def test_clocked_in_geocode_skips_plus_code_when_street_exists(
    monkeypatch,
    employee_factory,
    job_factory,
    scope_factory,
):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            payload = {
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "2WVH+V6 Calgary, AB, Canada",
                        "types": ["plus_code"],
                    },
                    {
                        "formatted_address": "123 Main St NW, Calgary, AB, Canada",
                        "types": ["street_address"],
                    },
                ],
            }
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5: _Resp())

    employee = employee_factory(company_id=1)
    job = job_factory(company_id=1)
    scope = scope_factory(company_id=1, job_id=job.id)

    db = SessionLocal()
    try:
        te = TimeEntry(
            time_entry_id="te-pluscode-1",
            company_id=1,
            employee_id=employee.id,
            job_id=job.id,
            scope_id=scope.id,
            started_at=datetime.now(timezone.utc),
            status="active",
            approval_status="pending",
        )
        db.add(te)
        db.commit()

        row = EventOutbox(
            company_id=1,
            event_type="TIME_ENTRY_CLOCKED_IN",
            idempotency_key="k-pluscode-1",
            payload={
                "time_entry_id": "te-pluscode-1",
                "clock_in_lat": 51.0447,
                "clock_in_lng": -114.0719,
            },
        )

        handle_time_entry_clocked_in(row, db)

        fresh = (
            db.query(TimeEntry)
            .filter(TimeEntry.company_id == 1, TimeEntry.time_entry_id == "te-pluscode-1")
            .first()
        )
        assert fresh is not None
        assert fresh.clock_in_address == "123 Main St NW, Calgary, AB, Canada"
        assert fresh.clock_in_address_source == "google"
    finally:
        db.close()

# Frontier Backend — AI Project Context (Master Brief)

## Mission
Build a production-grade workforce backend for Rivercrest/Baseline covering:
- Time tracking (clock in/out, time entries)
- Payroll domain (pay periods, payroll items)
- Job costing (job_cost_ledger)
- Event outbox (durable outbox for downstream processing)
- Tenant scoping by company_id across all domains

Success criteria (must be true)
1) `./scripts/test.sh` passes from a clean database.
2) `alembic upgrade head` works from an empty DB deterministically.
3) Constraints reflect production rules (do not weaken constraints to satisfy tests).
4) Company/tenant scoping enforced consistently (headers/company_id).

## Non-negotiable engineering rules
- Never redesign architecture without explicit approval.
- Never modify migrations already merged into main (create new migrations only).
- Never disable/relax FK/unique constraints just to pass tests.
- Prefer fixtures/factories over hardcoded IDs.
- Every step ends with:
  ✓ what changed
  ✓ why
  ✓ command to verify

## Current stack
- FastAPI
- SQLAlchemy ORM
- Alembic migrations
- Postgres
- pytest
- scripts/test.sh drops/recreates DB, runs alembic upgrade head, runs pytest

## Current known work
- Employees / Jobs / Scopes domain exists.
- Time entries endpoints exist.
- FK constraints exist from time_entries to employees/jobs/scopes.
- Event outbox table + model exists (event_outbox).
- There was recent churn around event_outbox migration + router integration.

## Current priority (execution order)
1) Stabilize schema + migrations: ensure event_outbox exists exactly once and migrations are correct.
2) Stabilize tests: all tests pass on clean DB.
3) Confirm outbox behavior: clock_out writes outbox row in same transaction; tenant scoped.
4) Restore/verify concurrency guard: unique active time entry per (company_id, employee_id) where status='active'.

## Out of scope (for now)
- New modules (waste management, email linking, cost control UI) until core backend is stable.


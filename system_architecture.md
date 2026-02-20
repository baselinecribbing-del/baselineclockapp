# Frontier Operational Systems --- System Architecture (Source of Truth)

Repo: frontier_backend Backend stack: FastAPI, SQLAlchemy ORM, Alembic
migrations, Postgres, Pytest CI workflow name: Frontier Operations

Primary goal of this document: Prevent architectural drift across chats,
contributors, and future refactors.

------------------------------------------------------------------------

## 0) Non-Negotiable Invariants

1.  Company Isolation

-   Every data access path that touches tenant data must enforce
    company_id.
-   Auth dependency must set request.state.company_id.
-   No cross-company reads or writes.

2.  Immutability

-   Job cost ledger entries are append-only.
-   Ledger immutability enforced via DB triggers and service
    protections.
-   Finalized financial data cannot be recalculated.

3.  Deterministic CI

-   All tests must pass deterministically in CI.
-   JWT secret behavior must not introduce randomness in tests.

4.  Migration Discipline

-   All schema changes go through Alembic.
-   No manual schema edits.
-   CI must run alembic upgrade head before tests.

------------------------------------------------------------------------

## 1) High-Level Architecture

Runtime Components:

-   FastAPI API Server Entry: app/main.py Routers:

    -   auth
    -   workflow_preview
    -   time_entries
    -   costing

-   Database: Postgres SQLAlchemy engine in app/database.py Alembic
    manages migrations.

-   Domain Services: app/services/\*

    -   auth_service
    -   time_engine_v10
    -   costing_service
    -   ledger_immutability
    -   workflow_service

Dependency Direction:

Routers → Services → Models/DB Core modules provide logging +
authorization.

Routers must not contain complex business logic.

------------------------------------------------------------------------

## 2) Current API Surface

Public: - GET / - GET /health

Auth: - POST /auth/token

Time Entries: - GET /time_entries/active - GET /time_entries/latest

Costing: - GET /costing/job/{job_id}/ledger - POST
/costing/post/labor/{pay_period_id} - POST /costing/post/production

Workflow Preview: - GET /preview/health - POST /preview/reset - GET
/preview/flows - POST /preview/start - GET /preview/executions - GET
/preview/{execution_id} - POST /preview/{execution_id}/submit - POST
/preview/{execution_id}/advance - POST /preview/{execution_id}/complete

------------------------------------------------------------------------

## 3) Security Model

Authentication: - JWT Bearer tokens issued via /auth/token. -
require_auth verifies token and sets request.state.company_id.

Authorization: - require_role(Role.X) enforces role-based access. - No
silent privilege escalation permitted in production mode.

------------------------------------------------------------------------

## 4) Testing Strategy

Pytest suite covers: - Clock-in concurrency - Clock-out protection - Job
cost ledger integrity - Workflow transaction rollback - Time engine
behavior

Tests must: - Enforce tenant isolation - Validate immutability
constraints - Fail on regression

------------------------------------------------------------------------

## 5) Backend Completion Definition

Backend is considered complete when:

1.  Stable API contract is defined and frozen.
2.  Core entities have defined workflows.
3.  Tenant isolation enforced everywhere.
4.  CI fully green.
5.  Migrations reproducible from clean database.

------------------------------------------------------------------------

## 6) Change Control

Any architectural change requires:

1.  Update to SYSTEM_ARCHITECTURE.md
2.  Code changes
3.  Tests added or updated
4.  CI passing

No architectural changes are accepted without updating this document.

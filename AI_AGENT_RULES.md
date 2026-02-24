# AI Agent Rules — frontier_backend

## Migration Safety Rules
- NEVER modify an existing alembic migration.
- NEVER insert application logic into alembic/versions.
- Migrations are append-only history.
- Any schema change requires a NEW migration revision.

## Database Discipline
- Database schema must always match alembic head.
- Tests must pass from a clean database.
- No disabling constraints to satisfy tests.

## Editing Rules
- Prefer modifying service or router code.
- Do not rewrite unrelated files.
- Changes must be minimal and reversible.

## Workflow
1. Inspect repository state
2. Propose change
3. Apply change
4. Run tests
5. Verify database

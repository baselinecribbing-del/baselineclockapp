from sqlalchemy import inspect, text


def table_exists(engine, table_name: str) -> bool:
    if engine is None:
        return False
    return inspect(engine).has_table(table_name)


def install_job_cost_ledger_immutability(engine) -> None:
    """
    Postgres-only: install triggers to block UPDATE/DELETE on job_cost_ledger.
    Safe to run multiple times (idempotent).
    """
    if engine is None:
        return

    # Only apply to PostgreSQL
    dialect = getattr(engine, "dialect", None)
    if dialect is None or getattr(dialect, "name", "") != "postgresql":
        return

    if not table_exists(engine, "job_cost_ledger"):
        return

    ddl = """
    CREATE OR REPLACE FUNCTION job_cost_ledger_block_mutation()
    RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'job_cost_ledger is immutable';
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_job_cost_ledger_block_update ON job_cost_ledger;
    CREATE TRIGGER trg_job_cost_ledger_block_update
    BEFORE UPDATE ON job_cost_ledger
    FOR EACH ROW
    EXECUTE FUNCTION job_cost_ledger_block_mutation();

    DROP TRIGGER IF EXISTS trg_job_cost_ledger_block_delete ON job_cost_ledger;
    CREATE TRIGGER trg_job_cost_ledger_block_delete
    BEFORE DELETE ON job_cost_ledger
    FOR EACH ROW
    EXECUTE FUNCTION job_cost_ledger_block_mutation();
    """

    with engine.begin() as conn:
        conn.execute(text(ddl))

import os
_default_test_secret = "test-jwt-secret-for-pytest-only-0000000000000000"
if len(os.environ.get("JWT_SECRET", "")) < 32:
    os.environ["JWT_SECRET"] = _default_test_secret

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ArthurS@localhost/frontier_test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import database


def _get_access_token(client, company_id: int, user_id: str = "test") -> str:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert isinstance(data, dict), f"token response not a JSON object: {data}"
    assert "access_token" in data, f"token response missing access_token: {data}"
    return data["access_token"]


def _ensure_database_exists(database_url: str) -> None:
    url = make_url(database_url)

    if not url.drivername.startswith("postgresql"):
        return

    db_name = url.database
    admin_url = url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if not exists:
                safe_db_name = db_name.replace('"', '""')
                conn.execute(text(f'CREATE DATABASE "{safe_db_name}"'))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _prepare_test_database() -> None:
    _ensure_database_exists(TEST_DATABASE_URL)

    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DATABASE_URL

    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        cwd=Path(__file__).resolve().parents[2],
        env=env,
    )

    database.configure_database()


@pytest.fixture(scope="function", autouse=True)
def _truncate_tables_between_tests():
    with database.engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename <> 'alembic_version'
                """
            )
        ).fetchall()

        table_names = [row[0] for row in rows]
        if table_names:
            quoted = ", ".join([f'"public"."{name}"' for name in table_names])
            conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))

    yield

    with database.engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename <> 'alembic_version'
                """
            )
        ).fetchall()

        table_names = [row[0] for row in rows]
        if table_names:
            quoted = ", ".join([f'"public"."{name}"' for name in table_names])
            conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))

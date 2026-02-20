from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from typing import Optional

from alembic import context
from sqlalchemy import create_engine, engine_from_config, pool
from sqlalchemy.engine import Connection

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import Base  # noqa: E402
from app.database import engine as app_engine  # noqa: E402
from app.models import time_entry, workflow_execution  # noqa: E402,F401
from app.models.job_cost_ledger import JobCostLedger  # noqa: E402,F401

try:
    from app.database import DATABASE_URL as APP_DATABASE_URL  # type: ignore  # noqa: E402
except Exception:
    APP_DATABASE_URL = None

config = context.config
if os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_db_url() -> str:
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    if APP_DATABASE_URL:
        return APP_DATABASE_URL
    raise RuntimeError("No database URL configured (DATABASE_URL or alembic.ini sqlalchemy.url)")


def run_migrations_offline() -> None:
    url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _configure_and_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        connectable = create_engine(env_url)
        with connectable.connect() as connection:
            _configure_and_run(connection)
        return

    connectable = None

    try:
        connectable = app_engine
    except Exception:
        connectable = None

    if connectable is not None:
        with connectable.connect() as connection:
            _configure_and_run(connection)
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _get_db_url()
    connectable2 = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable2.connect() as connection:
        _configure_and_run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

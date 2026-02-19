import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

Base = declarative_base()

DATABASE_URL = ""
engine = None
_configured_database_url = None


def _get_database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://ArthurS@localhost/baseline_workforce")


def configure_database() -> None:
    global DATABASE_URL, engine, _configured_database_url

    database_url = _get_database_url()

    if engine is not None and _configured_database_url == database_url:
        return

    engine = create_engine(database_url)
    SessionLocal.configure(bind=engine)
    DATABASE_URL = database_url
    _configured_database_url = database_url


configure_database()


def get_db():
    configure_database()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

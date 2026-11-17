"""
app/database.py — SQLAlchemy engine, session factory, and helpers.
"""

import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # required for SQLite + threads
    echo=False,
)


# Enable WAL mode for SQLite (better concurrent read/write performance)
@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency — yields a DB session per request
# ---------------------------------------------------------------------------

def get_db():
    """Dependency injected into FastAPI route handlers."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Initialise tables
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables that do not yet exist. Called at application startup."""
    from app import db_models  # noqa: F401 — registers models with Base
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised: %s", settings.database_url)


def check_db_health() -> bool:
    """Return True if the database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover
        logger.error("Database health check failed: %s", exc)
        return False

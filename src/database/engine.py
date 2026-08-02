"""SQLAlchemy engine factory supporting SQLite and PostgreSQL.

The engine URL is resolved from:
1. DATABASE_URL environment variable (highest priority)
2. config.yaml database.url setting
3. Default: sqlite:///data/f1_strategy.db
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, create_engine, event, text

from src.config import config

logger = logging.getLogger(__name__)

_engine: Engine | None = None


def get_engine(url: str | None = None) -> Engine:
    """Get or create the SQLAlchemy engine (singleton).

    Args:
        url: Optional override for the database URL.

    Returns:
        Configured SQLAlchemy Engine.
    """
    global _engine
    if _engine is not None and url is None:
        return _engine

    db_url = url or config.database.resolved_url
    logger.info("Database URL: %s", db_url.split("@")[-1] if "@" in db_url else db_url)

    engine = create_engine(
        db_url,
        echo=False,
        pool_pre_ping=True,
    )

    # Enable WAL mode and foreign keys for SQLite
    if db_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    if url is None:
        _engine = engine
    return engine


def init_db(engine: Engine | None = None) -> None:
    """Create all tables defined in the ORM models.

    Safe to call multiple times — uses CREATE IF NOT EXISTS.
    """
    from src.database.models import Base

    if engine is None:
        engine = get_engine()

    Base.metadata.create_all(engine)
    logger.info("Database tables created/verified")


def reset_engine() -> None:
    """Reset the engine singleton (useful for testing)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None

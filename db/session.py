from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.logger import get_logger
from backend.core.settings import database_url
from backend.db.models import Base

logger = get_logger(__name__)

_engine = None
SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL / FLUXTRADE_DATABASE_URL is not set")
    if _engine is None:
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)
    return _engine


def configure_session() -> None:
    global SessionLocal
    if SessionLocal is not None:
        return
    if not database_url():
        return
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables if they do not exist (idempotent)."""
    url = database_url()
    if not url:
        logger.info("init_db skipped: no database URL configured")
        return
    configure_session()
    Base.metadata.create_all(bind=get_engine())
    logger.info("Database tables ensured (create_all).")


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    configure_session()
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

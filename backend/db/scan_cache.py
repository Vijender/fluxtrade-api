from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from backend.core.logger import get_logger
from backend.core.settings import database_url, scan_cache_enabled, scan_cache_ttl_seconds
from backend.db.models import ScanResult
from backend.db.session import SessionLocal, configure_session
from backend.engine.spreads.models import VolatilityMode

logger = get_logger(__name__)


def get_cached_scan(ticker: str, mode: VolatilityMode) -> dict[str, Any] | None:
    if not scan_cache_enabled() or not database_url():
        return None
    sym = ticker.strip().upper()
    mode_s = mode.value if isinstance(mode, VolatilityMode) else str(mode)
    try:
        configure_session()
        if SessionLocal is None:
            return None
        session = SessionLocal()
        try:
            row = session.scalars(
                select(ScanResult).where(
                    ScanResult.ticker == sym,
                    ScanResult.mode == mode_s,
                    ScanResult.expires_at > datetime.now(timezone.utc),
                )
            ).first()
            if row:
                return dict(row.payload)
            return None
        finally:
            session.close()
    except Exception:
        logger.exception("scan_results read failed for %s %s", sym, mode_s)
        return None


def set_cached_scan(ticker: str, mode: VolatilityMode, payload: dict[str, Any]) -> None:
    if not scan_cache_enabled() or not database_url():
        return
    sym = ticker.strip().upper()
    mode_s = mode.value if isinstance(mode, VolatilityMode) else str(mode)
    ttl = scan_cache_ttl_seconds()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl)
    try:
        configure_session()
        if SessionLocal is None:
            return
        session = SessionLocal()
        try:
            session.execute(
                delete(ScanResult).where(
                    ScanResult.ticker == sym,
                    ScanResult.mode == mode_s,
                )
            )
            session.add(
                ScanResult(
                    ticker=sym,
                    mode=mode_s,
                    payload=payload,
                    expires_at=expires,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    except Exception:
        logger.exception("scan_results write failed for %s %s", sym, mode_s)

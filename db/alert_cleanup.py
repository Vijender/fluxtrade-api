from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from core.logger import get_logger
from core.settings import alert_retention_days
from db.models import Alert, ScanResult
from db.session import SessionLocal, configure_session

logger = get_logger(__name__)


def purge_expired_alerts() -> int:
    """Delete ``alerts`` rows older than FLUXTRADE_ALERT_RETENTION_DAYS (2–5)."""
    configure_session()
    if SessionLocal is None:
        return 0
    days = alert_retention_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = SessionLocal()
    try:
        res = session.execute(delete(Alert).where(Alert.created_at < cutoff))
        session.commit()
        n = res.rowcount or 0
        if n:
            logger.info("Purged %s alert row(s) older than %s days", n, days)
        return n
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def purge_expired_scan_results() -> int:
    """Delete ``scan_results`` rows past ``expires_at``."""
    configure_session()
    if SessionLocal is None:
        return 0
    now = datetime.now(timezone.utc)
    session = SessionLocal()
    try:
        res = session.execute(delete(ScanResult).where(ScanResult.expires_at < now))
        session.commit()
        n = res.rowcount or 0
        if n:
            logger.info("Purged %s expired scan_results row(s)", n)
        return n
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def purge_expired_storage() -> dict[str, int]:
    """Run all retention jobs (alerts + scan cache)."""
    return {
        "alerts_deleted": purge_expired_alerts(),
        "scan_results_deleted": purge_expired_scan_results(),
    }

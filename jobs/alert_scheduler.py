"""
APScheduler: Monday–Sunday, America/Los_Angeles — every hour at :00 from
5:00 through 23:00 (5:00 AM through 11:59 PM local). The batch runner also
enforces the same window if a job fires outside it.

Requires: pip install APScheduler  (see requirements.txt)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from zoneinfo import ZoneInfo

from core.logger import get_logger
from core.settings import alert_retention_days, database_url, scan_cache_enabled
from engine.alerts.batch_runner import (
    LAST_ALERT_BATCH_RESULT,
    run_all_users_alert_batch,
)

logger = get_logger(__name__)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _APSCHEDULER_AVAILABLE = True
except ModuleNotFoundError:
    BackgroundScheduler = None  # type: ignore[misc, assignment]
    CronTrigger = None  # type: ignore[misc, assignment]
    _APSCHEDULER_AVAILABLE = False

_scheduler: Any = None


def get_alert_scheduler_status() -> dict[str, Any]:
    """Diagnostics for why alerts may not have run (call from HTTP handler)."""
    disabled = os.environ.get("FLUXTRADE_DISABLE_ALERT_SCHEDULER", "").lower() in (
        "1",
        "true",
        "yes",
    )
    out: dict[str, Any] = {
        "apscheduler_installed": _APSCHEDULER_AVAILABLE,
        "scheduler_disabled_by_env": disabled,
        "scheduler_thread_running": _scheduler is not None,
        "timezone": "America/Los_Angeles",
        "cron": "Every day LA: hourly :00 for hours 5–23 (5:00 AM–11:59 PM); batch also enforces window",
        "last_batch_result": dict(LAST_ALERT_BATCH_RESULT or {}),
        "database_configured": bool(database_url()),
        "alert_retention_days": alert_retention_days(),
        "scan_cache_enabled": scan_cache_enabled(),
    }
    if _scheduler is not None:
        jobs = _scheduler.get_jobs()
        out["jobs"] = [
            {
                "id": j.id,
                "next_run_time": j.next_run_time.isoformat()
                if j.next_run_time
                else None,
            }
            for j in jobs
        ]
    else:
        out["jobs"] = []
    return out


def _run_startup_batch_delayed() -> None:
    def _work() -> None:
        time.sleep(4)
        logger.info("Running one-shot alert batch (FLUXTRADE_ALERT_BATCH_RUN_ON_STARTUP).")
        try:
            run_all_users_alert_batch()
        except Exception:
            logger.exception("Startup alert batch crashed")

    threading.Thread(target=_work, daemon=True, name="fluxtrade-alert-startup").start()


def start_alert_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    if not _APSCHEDULER_AVAILABLE:
        logger.warning(
            "APScheduler is not installed; hourly TRADE batch is disabled. "
            "Run: pip install APScheduler   or   pip install -r requirements.txt"
        )
        return
    if os.environ.get("FLUXTRADE_DISABLE_ALERT_SCHEDULER", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.info("Alert scheduler disabled (FLUXTRADE_DISABLE_ALERT_SCHEDULER).")
        return

    assert BackgroundScheduler is not None and CronTrigger is not None
    tz = ZoneInfo("America/Los_Angeles")
    _scheduler = BackgroundScheduler(timezone=tz)
    # Hours 5–23 every calendar day (Mon–Sun). Omit day_of_week so APScheduler
    # does not mis-parse ranges; batch_runner still enforces the LA window.
    _scheduler.add_job(
        run_all_users_alert_batch,
        CronTrigger(hour="5-23", minute=0, timezone=tz),
        id="fluxtrade_alert_batch",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3540,
    )
    _scheduler.start()

    for j in _scheduler.get_jobs():
        nrt = j.next_run_time.isoformat() if j.next_run_time else "unknown"
        logger.info("Alert job %r next run (server TZ): %s", j.id, nrt)

    if os.environ.get("FLUXTRADE_ALERT_BATCH_RUN_ON_STARTUP", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        _run_startup_batch_delayed()


def stop_alert_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Alert scheduler stopped.")

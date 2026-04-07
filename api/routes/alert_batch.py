import os

from fastapi import APIRouter, Header, HTTPException, Query

from backend.engine.alerts.batch_runner import run_all_users_alert_batch
from backend.jobs.alert_scheduler import get_alert_scheduler_status

router = APIRouter(tags=["alerts"])


@router.get("/internal/scheduler/status")
def alert_scheduler_status() -> dict:
    """
    Why alerts might not have run: APScheduler missing, env disabled, next fire time,
    and last batch return payload (skip reason, user counts, errors).
    """
    return get_alert_scheduler_status()


@router.post("/internal/batch/run")
def trigger_alert_batch(
    force: bool = Query(
        False,
        description=(
            "If true, run outside the normal Mon–Sun 5:00 AM–11:59 PM "
            "America/Los_Angeles window."
        ),
    ),
    x_fluxtrade_secret: str | None = Header(default=None, alias="X-FluxTrade-Secret"),
) -> dict:
    """
    Manual batch run (same logic as the scheduler). Protect with FLUXTRADE_ALERT_BATCH_SECRET.
    Use ``?force=1`` to test outside the normal Mon–Sun 5:00 AM–11:59 PM LA window.
    """
    expected = os.environ.get("FLUXTRADE_ALERT_BATCH_SECRET", "").strip()
    if not expected or x_fluxtrade_secret != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing secret")
    return run_all_users_alert_batch(bypass_schedule=force)

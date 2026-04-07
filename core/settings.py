"""
Runtime configuration: Postgres only (DATABASE_URL / FLUXTRADE_DATABASE_URL).
"""

from __future__ import annotations

import os


def database_url() -> str | None:
    """SQLAlchemy URL. Render sets DATABASE_URL; we also accept FLUXTRADE_DATABASE_URL."""
    raw = (
        os.environ.get("FLUXTRADE_DATABASE_URL", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )
    if not raw:
        return None
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg2://" + raw[len("postgres://") :]
    elif raw.startswith("postgresql://") and "+psycopg2" not in raw.split("://", 1)[0]:
        raw = "postgresql+psycopg2://" + raw[len("postgresql://") :]
    return raw


def jwt_secret() -> str:
    return os.environ.get("FLUXTRADE_JWT_SECRET", "").strip()


def jwt_expire_hours() -> int:
    try:
        return max(1, int(os.environ.get("FLUXTRADE_JWT_EXPIRE_HOURS", "168")))
    except ValueError:
        return 168


def alert_retention_days() -> int:
    try:
        d = int(os.environ.get("FLUXTRADE_ALERT_RETENTION_DAYS", "5"))
    except ValueError:
        d = 5
    return max(2, min(5, d))


def scan_cache_enabled() -> bool:
    return os.environ.get("FLUXTRADE_SCAN_CACHE_ENABLED", "").lower() in (
        "1",
        "true",
        "yes",
    )


def scan_cache_ttl_seconds() -> int:
    try:
        return max(60, int(os.environ.get("FLUXTRADE_SCAN_CACHE_TTL_SECONDS", "900")))
    except ValueError:
        return 900


def enforce_https_redirect() -> bool:
    """
    Redirect HTTP → HTTPS. Requires uvicorn ``--proxy-headers`` behind Render/nginx
    so ``X-Forwarded-Proto`` is trusted (otherwise you can get redirect loops).

    On when ``FLUXTRADE_ENFORCE_HTTPS=1`` or ``RENDER=true``; off if
    ``FLUXTRADE_DISABLE_HTTPS_REDIRECT=1``.
    """
    if os.environ.get("FLUXTRADE_DISABLE_HTTPS_REDIRECT", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    if os.environ.get("FLUXTRADE_ENFORCE_HTTPS", "").lower() in ("1", "true", "yes"):
        return True
    return os.environ.get("RENDER", "").lower() == "true"


def hsts_max_age_seconds() -> int:
    try:
        return max(0, int(os.environ.get("FLUXTRADE_HSTS_MAX_AGE", "31536000")))
    except ValueError:
        return 31536000

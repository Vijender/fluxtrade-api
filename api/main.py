from contextlib import asynccontextmanager

from core.env_loader import load_fluxtrade_env

load_fluxtrade_env()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from api.routes.alert_batch import router as alert_batch_router
from api.routes.auth import router as auth_router
from api.routes.spreads import router as spreads_router
from api.routes.user_data import router as user_data_router
from api.routes.user_settings import router as user_settings_router
from core.logger import get_logger
from core.secure_api_middleware import SecurityHeadersMiddleware
from core.settings import database_url, enforce_https_redirect
from db.alert_cleanup import purge_expired_storage
from db.session import init_db
from jobs.alert_scheduler import start_alert_scheduler, stop_alert_scheduler

_logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if database_url():
        try:
            purge_expired_storage()
        except Exception:
            _logger.exception("Startup storage purge failed (DB reachable?)")
    start_alert_scheduler()
    yield
    stop_alert_scheduler()


app = FastAPI(
    title="FluxTrade backend",
    description="Options spread scanner API for the FluxTrade dashboard",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(spreads_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(user_data_router, prefix="/api")
app.include_router(alert_batch_router, prefix="/api")
app.include_router(user_settings_router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if enforce_https_redirect():
    app.add_middleware(HTTPSRedirectMiddleware)

# Outermost: runs first on the request; adds headers to every response (including redirects).
app.add_middleware(SecurityHeadersMiddleware)


@app.get("/")
def root():
    return {"service": "fluxtrade-backend", "docs": "/docs"}


@app.get("/health")
def health():
    from core.settings import (
        alert_retention_days,
        database_url,
        jwt_secret,
        scan_cache_enabled,
        scan_cache_ttl_seconds,
    )

    return {
        "status": "ok",
        "database_configured": bool(database_url()),
        "jwt_configured": bool(jwt_secret()),
        "alert_retention_days": alert_retention_days(),
        "scan_cache_enabled": scan_cache_enabled(),
        "scan_cache_ttl_seconds": scan_cache_ttl_seconds(),
        "https_redirect_enforced": enforce_https_redirect(),
    }

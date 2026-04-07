"""
HTTPS-oriented hardening: security headers on every response; optional HTTP→HTTPS redirect.
Requires reverse proxy to set X-Forwarded-Proto (use uvicorn --proxy-headers on Render).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.core.settings import hsts_max_age_seconds


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline headers for API responses; HSTS when the request is treated as HTTPS."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy",
            "strict-origin-when-cross-origin",
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")

        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
        if proto == "https":
            age = hsts_max_age_seconds()
            if age > 0:
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    f"max-age={age}; includeSubDomains",
                )
        return response

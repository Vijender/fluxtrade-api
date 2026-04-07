"""SMTP settings and profile summary (Postgres + JWT, email identifies the user)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from backend.api.auth_util import open_authenticated_session
from backend.core.logger import get_logger
from backend.core.smtp_crypto import encrypt_smtp_password
from backend.db.models import Strategy, Trade, Watchlist

logger = get_logger(__name__)

router = APIRouter(tags=["user-settings"])


class SmtpSaveBody(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(587, ge=1, le=65535)
    user: str = Field(..., min_length=1, description="SMTP login (often your email)")
    password: str = Field(
        default="",
        description="SMTP password; leave empty to keep existing encrypted secret",
    )
    mail_from: str | None = Field(
        default=None,
        description="Optional From address; defaults to SMTP user",
    )


@router.post("/user/smtp")
def save_user_smtp(
    body: SmtpSaveBody,
    authorization: str | None = Header(default=None),
) -> dict:
    if not os.environ.get("FLUXTRADE_CREDENTIALS_FERNET_KEY", "").strip():
        raise HTTPException(
            status_code=503,
            detail="Server missing FLUXTRADE_CREDENTIALS_FERNET_KEY",
        )

    user, session = open_authenticated_session(authorization)
    try:
        existing_enc = str(user.smtp_password_enc or "").strip()
        pwd = (body.password or "").strip()
        if pwd:
            enc = encrypt_smtp_password(pwd)
            if not enc:
                raise HTTPException(status_code=500, detail="Encryption failed")
        else:
            if not existing_enc:
                raise HTTPException(
                    status_code=400,
                    detail="Password is required when no SMTP secret is saved yet",
                )
            enc = existing_enc

        from_addr = (body.mail_from or body.user).strip()
        user.smtp_host = body.host.strip()
        user.smtp_port = body.port
        user.smtp_user = body.user.strip()
        user.smtp_password_enc = enc
        user.smtp_from = from_addr
        session.add(user)
        session.commit()
        logger.info("User %s saved SMTP host=%s", user.email, body.host.strip())
        return {"ok": True, "email": user.email}
    finally:
        session.close()


@router.delete("/user/smtp")
def clear_user_smtp(authorization: str | None = Header(default=None)) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        user.smtp_host = ""
        user.smtp_port = 587
        user.smtp_user = ""
        user.smtp_password_enc = ""
        user.smtp_from = ""
        session.add(user)
        session.commit()
        return {"ok": True, "email": user.email}
    finally:
        session.close()


@router.get("/user/me")
def get_me(authorization: str | None = Header(default=None)) -> dict:
    user, session = open_authenticated_session(authorization)
    try:
        watchlist = session.scalars(
            select(Watchlist.symbol)
            .where(Watchlist.user_id == user.id)
            .order_by(Watchlist.sort_order, Watchlist.symbol)
        ).all()
        n_strategies = session.scalar(
            select(func.count()).select_from(Strategy).where(Strategy.user_id == user.id)
        )
        n_trades = session.scalar(
            select(func.count()).select_from(Trade).where(Trade.user_id == user.id)
        )
        n_watch = session.scalar(
            select(func.count()).select_from(Watchlist).where(Watchlist.user_id == user.id)
        )
        return {
            "email": user.email,
            "user_id": str(user.id),
            "email_verified": user.email_verified,
            "watchlist": [str(s).upper() for s in watchlist],
            "watchlist_count": int(n_watch or 0),
            "strategies_count": int(n_strategies or 0),
            "saved_trades_count": int(n_trades or 0),
            "alerts_email_enabled": user.alerts_email_enabled,
        }
    finally:
        session.close()

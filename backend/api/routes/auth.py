"""
Register / login: Postgres users identified by email; JWT includes sub + email.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from backend.core.logger import get_logger
from backend.core.security import create_access_token, hash_password, verify_password
from backend.core.settings import database_url, jwt_secret
from backend.db.models import User
from backend.db.session import configure_session, SessionLocal

logger = get_logger(__name__)

router = APIRouter(tags=["auth"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


def _require_db_auth() -> None:
    if not database_url():
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL or FLUXTRADE_DATABASE_URL is not configured",
        )
    if not jwt_secret():
        raise HTTPException(
            status_code=503,
            detail="FLUXTRADE_JWT_SECRET is not configured",
        )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


@router.post("/auth/register")
def register(body: RegisterBody) -> dict:
    _require_db_auth()
    configure_session()
    assert SessionLocal is not None
    email = _normalize_email(str(body.email))

    session = SessionLocal()
    try:
        existing = session.scalars(select(User).where(User.email == email)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        user = User(
            email=email,
            email_verified=True,
            password_hash=hash_password(body.password),
            alert_trade_sent_signatures=[],
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_access_token(user.id, user.email)
        logger.info("Registered user %s", email)
        return {
            "ok": True,
            "email": user.email,
            "access_token": token,
            "token_type": "bearer",
            "user_id": str(user.id),
        }
    finally:
        session.close()


@router.post("/auth/login")
def login(body: LoginBody) -> dict:
    _require_db_auth()
    configure_session()
    assert SessionLocal is not None
    email = _normalize_email(str(body.email))

    session = SessionLocal()
    try:
        user = session.scalars(select(User).where(User.email == email)).first()
        if not user or not user.password_hash:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token = create_access_token(user.id, user.email)
        return {
            "ok": True,
            "email": user.email,
            "access_token": token,
            "token_type": "bearer",
            "user_id": str(user.id),
        }
    finally:
        session.close()

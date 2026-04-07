"""Bearer JWT: identify user by id + email claim (must match database)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.security import decode_access_token
from core.settings import database_url, jwt_secret
from db.models import User
from db.session import SessionLocal, configure_session


def verify_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization[7:].strip()


def open_authenticated_session(authorization: str | None) -> tuple[User, Session]:
    if not database_url():
        raise HTTPException(status_code=503, detail="Database is not configured")
    if not jwt_secret():
        raise HTTPException(status_code=503, detail="FLUXTRADE_JWT_SECRET is not configured")
    token = verify_bearer(authorization)
    try:
        uid, email = decode_access_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from e

    configure_session()
    assert SessionLocal is not None
    session = SessionLocal()
    user = session.get(User, uid)
    if not user or user.email.lower() != email.lower():
        session.close()
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user, session

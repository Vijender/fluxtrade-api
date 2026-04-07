from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from backend.core.settings import jwt_expire_hours, jwt_secret

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def create_access_token(user_id: uuid.UUID, email: str) -> str:
    secret = jwt_secret()
    if not secret:
        raise RuntimeError("FLUXTRADE_JWT_SECRET is not set")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email.strip().lower(),
        "iat": now,
        "exp": now + timedelta(hours=jwt_expire_hours()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str) -> tuple[uuid.UUID, str]:
    """Returns (user_id, email) from JWT."""
    secret = jwt_secret()
    if not secret:
        raise RuntimeError("FLUXTRADE_JWT_SECRET is not set")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise ValueError("invalid token") from e
    sub = payload.get("sub")
    email = payload.get("email")
    if not sub or not email:
        raise ValueError("missing sub or email")
    return uuid.UUID(str(sub)), str(email).strip().lower()

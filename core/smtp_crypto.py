"""Encrypt/decrypt user SMTP passwords (Fernet). Set FLUXTRADE_CREDENTIALS_FERNET_KEY."""

from __future__ import annotations

import os

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get("FLUXTRADE_CREDENTIALS_FERNET_KEY", "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet

    _fernet = Fernet(key.encode("ascii"))
    return _fernet


def encrypt_smtp_password(plain: str) -> str | None:
    f = _get_fernet()
    if not f:
        return None
    return f.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_smtp_password(token: str) -> str | None:
    if not token or not str(token).strip():
        return None
    f = _get_fernet()
    if not f:
        return None
    try:
        return f.decrypt(str(token).strip().encode("ascii")).decode("utf-8")
    except Exception:
        return None

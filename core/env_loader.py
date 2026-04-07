"""
Load environment variables from repo-root `.env` then `backend/.env` (backend wins on duplicate keys).
Ensures the same root `.env` used by Vite (VITE_*) is visible to the FastAPI / batch jobs.
"""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    # core/env_loader.py is under the repository root.
    return Path(__file__).resolve().parents[1]


def load_fluxtrade_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    root = _repo_root()
    root_env = root / ".env"
    backend_env = root / "backend" / ".env"

    if root_env.is_file():
        load_dotenv(root_env, override=False)
    if backend_env.is_file():
        load_dotenv(backend_env, override=True)

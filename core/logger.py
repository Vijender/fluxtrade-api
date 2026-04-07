"""Application logging (stdlib)."""

from __future__ import annotations

import logging
import os


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if not log.handlers:
        level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        log.setLevel(getattr(logging, level_name, logging.INFO))
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        log.addHandler(handler)
    return log

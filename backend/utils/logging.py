from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from backend.config import APP_NAME, LOGS_DIR

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    logger = logging.getLogger(APP_NAME)
    if _configured:
        return logger

    logger.setLevel(level)
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    log_file = LOGS_DIR / "leia.log"
    rotating = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    rotating.setFormatter(fmt)
    logger.addHandler(rotating)

    _configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    root = setup_logging()
    return root.getChild(name) if name else root

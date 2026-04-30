from __future__ import annotations

import logging
from pathlib import Path

from options_dashboard.config import BASE_DIR

LOG_FILE = BASE_DIR / "logs" / "options_builder.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def log_step(message: str) -> None:
    logging.info(message)


def log_error(message: str, e: Exception | None = None) -> None:
    logging.error(f"{message} | {str(e) if e else ''}", exc_info=True)

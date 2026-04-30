from __future__ import annotations

import logging

from options_dashboard.config import BASE_DIR

LOG_FILE = BASE_DIR / "logs" / "options_builder.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

LOGGER_NAME = "options_builder"
logger = logging.getLogger(LOGGER_NAME)
if not logger.handlers:
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

# Reduce noisy 3rd-party logs that can block/flood in Streamlit reruns.
logging.getLogger("ib_insync").setLevel(logging.WARNING)
logging.getLogger("eventkit").setLevel(logging.WARNING)


def log_step(message: str) -> None:
    logger.info(message)


def log_error(message: str, e: Exception | None = None) -> None:
    logger.error(f"{message} | {str(e) if e else ''}", exc_info=True)

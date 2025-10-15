"""
Logging setup providing JSON-formatted structured logs.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict


class JsonLogFormatter(logging.Formatter):
    """Logging formatter that outputs JSON objects per record."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_payload["exc_info"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_payload"):
            extra_payload = getattr(record, "extra_payload")
            if isinstance(extra_payload, dict):
                log_payload.update(extra_payload)

        return json.dumps(log_payload, ensure_ascii=False)


def configure_logging(log_level: str) -> None:
    """Configure root logging with JSON formatting."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Avoid duplicate handlers when reconfigured (tests).
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())

    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    # Reduce noise from libraries unless overridden.
    for noisy_logger in ("urllib3", "apscheduler", "requests"):
        logging.getLogger(noisy_logger).setLevel(os.environ.get("LIB_LOG_LEVEL", "WARNING"))


"""Structured logging helpers for the PC Monitor backend."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_CONFIGURED = False

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}

#: Substrings that must never reach the log stream.
_SECRET_HINTS = (
    "token", "password", "secret", "private_key", "authorization", "cookie",
    "credential", "apikey", "api_key",
)


class RedactingFilter(logging.Filter):
    """Removes anything that looks like a secret from the record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        for key, value in list(record.__dict__.items()):
            if key in _RESERVED or not isinstance(value, (str, int, float, bool)):
                continue
            lowered = key.lower()
            if any(hint in lowered for hint in _SECRET_HINTS):
                record.__dict__[key] = "[redacted]"
                continue
            if isinstance(value, str) and _looks_like_secret(value):
                record.__dict__[key] = "[redacted]"
        return True


def _looks_like_secret(value: str) -> bool:
    lowered = value.lower()
    if lowered.startswith("-----begin") or "private key" in lowered:
        return True
    return lowered.startswith(("bearer ", "basic ")) or "password=" in lowered


class JsonFormatter(logging.Formatter):
    """Emits one JSON object per log line (nice for log shippers)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool, type(None))):
                payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO", app_name: str = "pc-monitor") -> logging.Logger:
    """Configure root logging once; returns the application logger."""
    global _CONFIGURED
    logger = logging.getLogger(app_name)
    if _CONFIGURED:
        logger.setLevel(level.upper())
        return logger

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Uvicorn keeps its own handlers; route them through the same formatter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True

    logging.captureWarnings(True)
    _CONFIGURED = True
    return logger


def get_logger_legacy(name: str = "pc-monitor") -> logging.Logger:
    return logging.getLogger(name)


class StructuredLogger:
    """Thin wrapper that turns keyword context into structured log fields.

    Usage::

        logger = get_logger(__name__)
        logger.info("device_registered", "new device registered", deviceId="PC-1")
    """

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    @property
    def raw(self) -> logging.Logger:
        return self._logger

    def _emit(
        self,
        level: int,
        event: str,
        message: str = "",
        *,
        exc_info: bool = False,
        **context: Any,
    ) -> None:
        extra = {"event": event}
        for key, value in context.items():
            if key in _RESERVED or key in {"event", "exc_info"}:
                continue
            extra[key] = value
        self._logger.log(level, message or event, extra=extra, exc_info=exc_info)

    def debug(self, event: str, message: str = "", **context: Any) -> None:
        self._emit(logging.DEBUG, event, message, **context)

    def info(self, event: str, message: str = "", **context: Any) -> None:
        self._emit(logging.INFO, event, message, **context)

    def warning(self, event: str, message: str = "", **context: Any) -> None:
        self._emit(logging.WARNING, event, message, **context)

    def error(self, event: str, message: str = "", **context: Any) -> None:
        self._emit(logging.ERROR, event, message, **context)

    def exception(self, event: str, message: str = "", **context: Any) -> None:
        self._emit(logging.ERROR, event, message, exc_info=True, **context)


def get_logger(name: str = "pc-monitor") -> StructuredLogger:
    """Return a structured logger (call sites pass ``event, message, **context``)."""
    return StructuredLogger(name)
"""Local logging for the Windows agent.

Logs live at ``%LOCALAPPDATA%\\PC-Monitor\\logs\\agent.log`` and are rotated so
they never grow without bound.  Tokens and other secrets are never written.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

LOG_FILENAME = "agent.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3

_SECRET_MARKERS = ("token", "password", "secret", "private_key", "authorization")
_configured = False


def app_data_dir() -> Path:
    """``%LOCALAPPDATA%\\PC-Monitor`` (falls back to ``~/.pc-monitor``)."""
    override = os.environ.get("PC_MONITOR_HOME")
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "PC-Monitor"
    return Path.home() / ".pc-monitor"


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


class SecretRedactingFilter(logging.Filter):
    """Belt-and-braces guard: scrub anything that looks like a credential."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        for key, value in list(record.__dict__.items()):
            if not isinstance(value, str):
                continue
            lowered = key.lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                record.__dict__[key] = "[redacted]"
                continue
            for marker in _SECRET_MARKERS:
                token_prefix = f"{marker}="
                if token_prefix in value.lower():
                    record.__dict__[key] = "[redacted]"
                    break
        return True


_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


class StructuredLogger:
    """Logger that accepts ``logger.info(event, message, **context)``."""

    def __init__(self, name: str = "pc-monitor-agent") -> None:
        self._logger = logging.getLogger(name)

    @property
    def raw(self) -> logging.Logger:
        return self._logger

    def _emit(self, level: int, event: str, message: str = "", **context: object) -> None:
        extra = {"event": event}
        for key, value in context.items():
            if key in _RESERVED or key in {"event", "exc_info"}:
                continue
            extra[key] = value
        self._logger.log(level, message or event, extra=extra)

    def debug(self, event: str, message: str = "", **context: object) -> None:
        self._emit(logging.DEBUG, event, message, **context)

    def info(self, event: str, message: str = "", **context: object) -> None:
        self._emit(logging.INFO, event, message, **context)

    def warning(self, event: str, message: str = "", **context: object) -> None:
        self._emit(logging.WARNING, event, message, **context)

    def error(self, event: str, message: str = "", **context: object) -> None:
        self._emit(logging.ERROR, event, message, **context)

    def exception(self, event: str, message: str = "", **context: object) -> None:
        self._logger.log(logging.ERROR, message or event, extra={"event": event}, exc_info=True)


def configure_logging(level: str = "INFO", console: Optional[bool] = None) -> logging.Logger:
    """Configure the agent logger (idempotent)."""
    global _configured
    logger = logging.getLogger("pc-monitor-agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    if _configured:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir() / LOG_FILENAME,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SecretRedactingFilter())
        logger.addHandler(file_handler)
    except OSError:  # read-only profile, locked file, ...
        logger.warning("log_file_unavailable", "continuing without a log file")

    if console if console is not None else sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(SecretRedactingFilter())
        logger.addHandler(stream_handler)

    _configured = True
    return logger


def get_logger() -> StructuredLogger:
    return StructuredLogger()
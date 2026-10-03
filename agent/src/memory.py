"""Physical memory telemetry (usage only - never file contents)."""

from __future__ import annotations

from typing import Any

import psutil

from src.logger import get_logger

logger = get_logger()


def collect() -> dict[str, Any]:
    """Total / used / available RAM and the usage percentage (never raises)."""
    try:
        memory = psutil.virtual_memory()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("memory_unavailable", "could not read memory metrics", error=str(exc))
        return {}
    return {
        "ramTotalMB": round(memory.total / (1024**2), 1),
        "ramUsedMB": round(memory.used / (1024**2), 1),
        "ramAvailableMB": round(memory.available / (1024**2), 1),
        "ramUsage": round(memory.percent, 2),
    }


def swap() -> dict[str, Any]:
    """Swap/pagefile usage - part of the same memory picture."""
    try:
        swap_memory = psutil.swap_memory()
    except Exception:  # pragma: no cover
        return {}
    return {
        "swapTotalMB": round(swap_memory.total / (1024**2), 1),
        "swapUsage": round(swap_memory.percent, 2),
    }
"""Disk telemetry: capacity and throughput.

Only capacity counters and I/O rates are read.  The agent never enumerates,
opens, reads or lists files and directories.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import psutil

from src.logger import get_logger

logger = get_logger()

_last_io_time: Optional[float] = None
_last_io_counters: Any = None

MBPS = 1024 * 1024


def root_path() -> str:
    """System volume (no directory listing is ever performed)."""
    import os
    import sys

    if sys.platform == "win32":
        drive = os.environ.get("SystemDrive", "C:")
        return drive + "\\"
    return "/"


def capacity() -> dict[str, Any]:
    """Total / used / free space and usage percentage for the system volume."""
    try:
        usage = psutil.disk_usage(root_path())
    except Exception as exc:  # pragma: no cover - permission/locked volume
        logger.warning("disk_usage_failed", "could not read disk capacity", error=str(exc))
        return {}
    return {
        "diskTotalGB": round(usage.total / (1024**3), 1),
        "diskUsedGB": round(usage.used / (1024**3), 1),
        "diskFreeGB": round(usage.free / (1024**3), 1),
        "diskUsage": round(usage.percent, 2),
    }


def throughput() -> dict[str, Any]:
    """Disk read/write speed in MB/s, measured between two samples."""
    global _last_io_time, _last_io_counters

    try:
        counters = psutil.disk_io_counters()
    except Exception as exc:  # pragma: no cover - permission dependent
        logger.debug("disk_io_unavailable", "disk throughput unavailable", error=str(exc))
        return {}

    now = time.time()
    previous_counters = _last_io_counters
    previous_time = _last_io_time
    _last_io_counters = counters
    _last_io_time = now

    if previous_counters is None or previous_time is None:
        # First sample establishes the baseline only.
        return {}

    elapsed = max(1e-6, now - previous_time)
    read_mbps = max(0.0, (counters.read_bytes - previous_counters.read_bytes) / elapsed / MBPS)
    write_mbps = max(0.0, (counters.write_bytes - previous_counters.write_bytes) / elapsed / MBPS)
    return {
        "diskReadMbps": round(read_mbps, 3),
        "diskWriteMbps": round(write_mbps, 3),
    }


def collect() -> dict[str, Any]:
    sample = capacity()
    sample.update(throughput())
    return sample
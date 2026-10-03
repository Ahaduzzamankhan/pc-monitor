"""Telemetry collector: assembles one sample from every sensor module.

Each sensor is invoked defensively - a failing sensor returns ``None`` for its
fields and never prevents the rest of the sample from being uploaded.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from src import __version__
from src import battery as battery_module
from src import cpu as cpu_module
from src import disk as disk_module
from src import gpu as gpu_module
from src import memory as memory_module
from src import network as network_module
from src import system as system_module
from src.logger import get_logger

logger = get_logger()

Sensor = Callable[[], dict[str, Any]]


def _safe(name: str, sensor: Sensor) -> dict[str, Any]:
    """Run one sensor; log and swallow any failure."""
    try:
        result = sensor()
    except Exception as exc:
        logger.warning("sensor_failed", "sensor raised, continuing", sensor=name, error=str(exc))
        return {}
    if not isinstance(result, dict):  # pragma: no cover - defensive
        logger.warning("sensor_bad_output", "sensor returned no mapping", sensor=name)
        return {}
    return result


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def collect(device_id: str, api_url: str = "", measure_latency: bool = False) -> dict[str, Any]:
    """Build one telemetry payload for ``device_id``.

    Returns a JSON-serialisable dict shaped exactly like
    ``backend/app/models/telemetry.py::TelemetryPayload``.
    """
    started = time.perf_counter()
    sample: dict[str, Any] = {"deviceId": device_id, "timestamp": utc_now_iso()}

    sample.update(_safe("cpu", cpu_module.collect))
    sample.update(_safe("gpu", gpu_module.collect))
    sample.update(_safe("memory", memory_module.collect))
    sample.update(_safe("disk", disk_module.collect))
    sample.update(_safe("network", lambda: network_module.collect(api_url, measure_latency)))
    sample.update(_safe("battery", battery_module.collect))

    uptime = system_module.uptime_seconds()
    if uptime is not None:
        sample["uptimeSeconds"] = uptime

    # None values are dropped so the backend stores only real readings.
    cleaned = {key: value for key, value in sample.items() if value is not None}
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.debug(
        "sample_collected",
        "telemetry sample assembled",
        deviceId=device_id,
        fields=len(cleaned),
        durationMs=duration_ms,
    )
    return cleaned


def agent_version() -> str:
    return __version__
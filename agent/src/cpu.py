"""CPU telemetry: usage, per-core usage, frequency, core counts, temperature."""

from __future__ import annotations

from typing import Any, Callable, Optional

import psutil

from src.logger import get_logger

logger = get_logger()

_temperature_available: Optional[bool] = None


def model() -> Optional[str]:
    """CPU model string (from the registry on Windows)."""
    from src.system import _cpu_model

    try:
        return _cpu_model()
    except Exception:  # pragma: no cover
        return None


def physical_cores() -> Optional[int]:
    try:
        count = psutil.cpu_count(logical=False)
        return int(count) if count else None
    except Exception:  # pragma: no cover
        return None


def logical_cores() -> Optional[int]:
    try:
        count = psutil.cpu_count(logical=True)
        return int(count) if count else None
    except Exception:  # pragma: no cover
        return None


def frequency_mhz() -> Optional[float]:
    """Current CPU frequency in MHz (None when the platform hides it)."""
    try:
        frequency = psutil.cpu_freq()
    except Exception:
        return None
    if frequency is None or not frequency.current:
        return None
    value = float(frequency.current)
    return round(value, 1) if value > 0 else None


def temperature_c() -> Optional[float]:
    """CPU package temperature in Celsius, or ``None`` when unavailable.

    Windows exposes no in-kernel thermal API to user mode, so this returns
    ``None`` unless a supported sensor source is present.  The dashboard renders
    "sensor unavailable" rather than a fabricated value.
    """
    global _temperature_available
    if _temperature_available is False:
        return None
    try:
        sensors = psutil.sensors_temperatures()  # type: ignore[attr-defined]
    except Exception:
        _temperature_available = False
        logger.debug("cpu_temperature_unsupported", "platform exposes no CPU thermal sensors")
        return None

    if not sensors:
        _temperature_available = False
        return None

    for name in ("coretemp", "k10temp", "cpu_thermal", "acpitz", "zenpower"):
        readings = sensors.get(name)
        if readings:
            package = next(
                (item for item in readings if "package" in item.label.lower()),
                readings[0],
            )
            if package.current:
                _temperature_available = True
                return round(float(package.current), 1)
    best = next((item.current for items in sensors.values() for item in items if item.current), None)
    if best is None:
        _temperature_available = False
        return None
    _temperature_available = True
    return round(float(best), 1)


def usage() -> float:
    """Overall CPU utilisation in percent (non-blocking, uses psutil's delta)."""
    return float(psutil.cpu_percent(interval=None))


def usage_per_core() -> Optional[list[float]]:
    """Per-logical-core utilisation in percent."""
    try:
        values = psutil.cpu_percent(interval=None, percpu=True)
    except Exception:  # pragma: no cover
        return None
    if not values:
        return None
    return [round(float(value), 1) for value in values]


def _measure(name: str, function: Any) -> Any:
    """Run one CPU reading; a failing sensor yields ``None`` instead of a crash."""
    try:
        return function()
    except Exception as exc:
        logger.debug("cpu_sensor_failed", "CPU reading unavailable", sensor=name, error=str(exc))
        return None


def collect() -> dict[str, Any]:
    """Return the CPU portion of a telemetry sample (never raises)."""
    total = _measure("usage", usage)
    sample: dict[str, Any] = {
        "cpuUsage": round(float(total), 2) if total is not None else None,
        "cpuPerCore": _measure("per_core", usage_per_core),
        "cpuFrequencyMHz": _measure("frequency", frequency_mhz),
        "cpuTemperature": _measure("temperature", temperature_c),
    }
    return {key: value for key, value in sample.items() if value is not None}
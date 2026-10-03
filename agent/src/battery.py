"""Battery telemetry (laptops only).

Desktop machines return an empty sample - the dashboard then renders the
battery row as "not applicable" instead of a fake 0%.
"""

from __future__ import annotations

from typing import Any, Optional

import psutil

from src.logger import get_logger

logger = get_logger()


def _windows_battery() -> Optional[dict[str, Any]]:
    """Fallback for machines where psutil cannot enumerate the battery."""
    import sys

    if sys.platform != "win32":
        return None
    try:
        import wmi  # type: ignore

        client = wmi.WMI()
        batteries = [
            device
            for device in client.Win32_Battery()
            if getattr(device, "BatteryStatus", None) is not None
        ]
        if not batteries:
            return None
        battery = batteries[0]
        charge = getattr(battery, "EstimatedChargeRemaining", None)
        status = getattr(battery, "BatteryStatus", None)
        return {
            "batteryPercent": float(charge) if charge is not None else None,
            "batteryCharging": status == 2,
            "batteryTimeLeftSeconds": None,
        }
    except Exception:  # pragma: no cover - optional dependency / hardware
        return None


def collect() -> dict[str, Any]:
    """Battery percentage, charging flag and remaining time (may be empty)."""
    try:
        battery = psutil.sensors_battery()
    except Exception as exc:  # pragma: no cover
        logger.debug("battery_unavailable", "battery sensor unavailable", error=str(exc))
        battery = None

    if battery is None:
        fallback = _windows_battery()
        if fallback:
            return {key: value for key, value in fallback.items() if value is not None}
        logger.debug("no_battery", "no battery present (desktop)")
        return {}

    sample: dict[str, Any] = {"batteryPercent": round(float(battery.percent), 1)}
    if battery.power_plugged is not None:
        sample["batteryCharging"] = bool(battery.power_plugged)
    if battery.secsleft is not None and battery.secsleft >= 0:
        sample["batteryTimeLeftSeconds"] = int(battery.secsleft)
    return sample


def is_laptop() -> bool:
    return bool(collect())
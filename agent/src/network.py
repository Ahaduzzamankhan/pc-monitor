"""Network telemetry: aggregate throughput and API latency.

Only byte counters are read from the OS.  The agent never inspects packets,
DNS names, visited hosts, URLs, browser history or any credential.
Loopback traffic is excluded so local chatter does not distort the numbers.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import psutil

from src.logger import get_logger

logger = get_logger()

MBPS = 1024 * 1024

_last_counters: Any = None
_last_time: Optional[float] = None


def _counters() -> Any:
    """Non-loopback byte counters."""
    counters = psutil.net_io_counters(pernic=False)
    if counters is None:
        return None
    loopback = psutil.net_io_counters(pernic=True).get("lo")
    if loopback is None:
        return counters
    return psutil.netio(
        bytes_sent=counters.bytes_sent - loopback.bytes_sent,
        bytes_recv=counters.bytes_recv - loopback.bytes_recv,
        packets_sent=counters.packets_sent - loopback.packets_sent,
        packets_recv=counters.packets_recv - loopback.packets_recv,
    )


def throughput() -> dict[str, Any]:
    """Download/upload speed in MB/s since the previous call."""
    global _last_counters, _last_time

    try:
        counters = _counters()
    except Exception as exc:  # pragma: no cover
        logger.debug("net_counters_failed", "network counters unavailable", error=str(exc))
        return {}

    now = time.time()
    previous, previous_time = _last_counters, _last_time
    _last_counters, _last_time = counters, now
    if previous is None or previous_time is None:
        return {}

    elapsed = max(1e-6, now - previous_time)
    download = max(0.0, (counters.bytes_recv - previous.bytes_recv) / elapsed / MBPS)
    upload = max(0.0, (counters.bytes_sent - previous.bytes_sent) / elapsed / MBPS)
    return {
        "downloadMbps": round(download, 3),
        "uploadMbps": round(upload, 3),
    }


def latency_ms(api_url: str, timeout: float = 3.0) -> Optional[float]:
    """Round-trip time to the monitoring API (optional, best effort)."""
    import httpx

    try:
        started = time.perf_counter()
        response = httpx.get(f"{api_url.rstrip('/')}/health", timeout=timeout)
        response.raise_for_status()
        return round((time.perf_counter() - started) * 1000, 2)
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("latency_probe_failed", "latency probe failed", error=str(exc))
        return None


def collect(api_url: str = "", measure_latency: bool = False) -> dict[str, Any]:
    sample = throughput()
    if measure_latency and api_url:
        latency = latency_ms(api_url)
        if latency is not None:
            sample["apiLatencyMs"] = latency
    return sample
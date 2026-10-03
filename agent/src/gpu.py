"""GPU telemetry.

Strategy (first that yields data wins):

1. **NVIDIA** via NVML (``nvidia-ml-py``/``pynvml``) when the driver exposes it.
2. **NVIDIA** fallback by parsing ``nvidia-smi`` output (no Python dependency).
3. **AMD / Intel** - model name via WMI; usage/temperature stay ``None``
   because those APIs are vendor specific and unavailable by default.

Everything degrades to ``None``: the agent never blocks or crashes on a machine
without a supported GPU, and the dashboard shows "unavailable" instead of a
made-up number.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Any, Optional

from src.logger import get_logger

logger = get_logger()

_nvml_handle: Any = None
_nvml_initialised = False
_model_cache: Optional[str] = None
_SUBPROCESS_TIMEOUT = 5


def _load_nvml() -> Any:
    """Initialise NVML once; returns ``None`` when unavailable."""
    global _nvml_handle, _nvml_initialised
    if _nvml_initialised:
        return _nvml_handle
    _nvml_initialised = True
    try:
        try:
            import pynvml  # type: ignore
        except ImportError:
            import nvidia_ml_py as pynvml  # type: ignore
        pynvml.nvmlInit()
        _nvml_handle = pynvml
        logger.info("gpu_nvml_ready", "NVML initialised")
    except Exception as exc:
        logger.info("gpu_nvml_unavailable", "NVML not available", error=str(exc))
        _nvml_handle = None
    return _nvml_handle


def _run(command: list[str]) -> Optional[str]:
    """Run a short-lived helper process without a console window."""
    try:
        startupinfo = None
        if sys.platform == "win32":  # avoid a console flash
            import subprocess as sp

            startupinfo = sp.STARTUPINFO()
            startupinfo.dwFlags |= sp.STARTF_USESHOWWINDOW
        completed = subprocess.run(  # noqa: S603 - fixed, argument-free commands
            command,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            startupinfo=startupinfo,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("gpu_command_failed", "helper command failed", error=str(exc))
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _nvidia_smi_query() -> Optional[dict[str, Any]]:
    """Parse a single ``nvidia-smi --query-gpu=... --format=csv,noheader`` call."""
    output = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output:
        return None
    line = next((item.strip() for item in output.splitlines() if item.strip()), None)
    if not line:
        return None
    parts = [item.strip() for item in line.split(",")]
    if len(parts) < 5:
        return None

    def number(value: str) -> Optional[float]:
        cleaned = value.replace("%", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    return {
        "model": parts[0],
        "gpuUsage": number(parts[1]),
        "gpuTemperature": number(parts[2]),
        "vramUsedMB": number(parts[3]),
        "vramTotalMB": number(parts[4]),
    }


def _wmi_gpu_names() -> list[str]:
    """GPU names from CIM (works for NVIDIA/AMD/Intel on Windows)."""
    if sys.platform != "win32":
        return []
    output = _run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ]
    )
    if not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _nvml_sample(handle: Any) -> Optional[dict[str, Any]]:
    try:
        count = handle.nvmlDeviceGetCount()
    except Exception:
        return None
    if not count:
        return None
    best: Optional[dict[str, Any]] = None
    for index in range(count):
        try:
            handle = handle  # noqa: PLW0127 - keep mypy quiet about shadowing
            device = handle.nvmlDeviceGetHandleByIndex(index)
            name = handle.nvmlDeviceGetName(device)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "ignore")
            usage = handle.nvmlDeviceGetUtilizationRates(device).gpu
            temperature = handle.nvmlDeviceGetTemperature(device, handle.NVML_TEMPERATURE_GPU)
            memory = handle.nvmlDeviceGetMemoryInfo(device)
            sample = {
                "model": name,
                "gpuUsage": float(usage),
                "gpuTemperature": float(temperature),
                "vramUsedMB": round(memory.used / (1024**2), 1),
                "vramTotalMB": round(memory.total / (1024**2), 1),
            }
            best = sample if best is None else _merge_gpu(best, sample)
        except Exception as exc:  # pragma: no cover - driver specific
            logger.debug("gpu_nvml_device_failed", "skipping GPU index", error=str(exc))
    return best


def _merge_gpu(primary: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Combine multi-GPU samples (max usage, max temperature, summed VRAM)."""
    return {
        "model": primary["model"],
        "gpuUsage": max(
            primary.get("gpuUsage") or 0.0, extra.get("gpuUsage") or 0.0
        ),
        "gpuTemperature": max(
            primary.get("gpuTemperature") or 0.0, extra.get("gpuTemperature") or 0.0
        ),
        "vramUsedMB": round(
            (primary.get("vramUsedMB") or 0.0) + (extra.get("vramUsedMB") or 0.0), 1
        ),
        "vramTotalMB": round(
            (primary.get("vramTotalMB") or 0.0) + (extra.get("vramTotalMB") or 0.0), 1
        ),
    }


def model_name() -> Optional[str]:
    """GPU model name (cached - it never changes while the agent runs)."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    handle = _load_nvml()
    if handle is not None:
        try:
            count = handle.nvmlDeviceGetCount()
            if count:
                device = handle.nvmlDeviceGetHandleByIndex(0)
                name = handle.nvmlDeviceGetName(device)
                _model_cache = name.decode("utf-8", "ignore") if isinstance(name, bytes) else str(name)
                return _model_cache
        except Exception:
            pass

    smi = _nvidia_smi_query()
    if smi and smi.get("model"):
        _model_cache = str(smi["model"])
        return _model_cache

    names = _wmi_gpu_names()
    # Filter out the virtual/basic display adapters Windows always reports.
    real = [
        name
        for name in names
        if not re.search(r"(microsoft basic|remote display|virtual|software)", name, re.I)
    ]
    _model_cache = (real or names or [None])[0] if (real or names) else None
    return _model_cache


def collect() -> dict[str, Any]:
    """GPU portion of a telemetry sample (empty when nothing is available).

    The GPU *model* is only reported at registration time - telemetry carries
    measurements only.
    """
    handle = _load_nvml()
    sample = _nvml_sample(handle) if handle is not None else None
    if sample is None:
        sample = _nvidia_smi_query()
    if sample is None:
        return {}
    return {
        key: value
        for key, value in sample.items()
        if key != "model" and value is not None
    }


def gpu_summary() -> dict[str, Any]:
    """Model name only - used during registration."""
    name = model_name()
    return {"model": name} if name else {}
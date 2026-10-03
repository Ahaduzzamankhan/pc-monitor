"""System information: Windows version, architecture, boot time, agent version."""

from __future__ import annotations

import os
import platform
import sys
import time
from typing import Any, Optional

import psutil

from src import __version__
from src.logger import get_logger

logger = get_logger()

_WINDOWS_BUILD_NAMES = {
    (10, 0, 22000): "Windows 11 21H2",
    (10, 0, 22621): "Windows 11 22H2",
    (10, 0, 25398): "Windows 11 24H2",
    (10, 0, 26100): "Windows 11 24H2",
}


def _windows_version() -> Optional[str]:
    """Read the product name from the registry (works without PowerShell)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:  # type: ignore[arg-defined]
            name = winreg.QueryValueEx(key, "ProductName")[0]  # type: ignore[attr-defined]
            build = int(winreg.QueryValueEx(key, "CurrentBuildNumber")[0])  # type: ignore[attr-defined]
            display = str(build)
            if name:
                # Windows 11 keeps the "Windows 10" product name for compatibility.
                major, minor = platform.windows_version()[:2] if hasattr(platform, "windows_version") else (10, 0)
                if build >= 22000:
                    name = name.replace("Windows 10", "Windows 11")
                return f"{name} (build {display})" if f"build {display}" not in str(name) else str(name)
            return f"Windows {major}.{minor} build {display}"
    except Exception as exc:  # pragma: no cover - registry access is environment specific
        logger.debug("windows_version_failed", "falling back to platform detection", error=str(exc))
        return platform.system()


def os_name() -> str:
    """Human readable OS string, e.g. ``Windows 11 Pro (build 22631)``."""
    if sys.platform == "win32":
        return _windows_version() or "Windows"
    return f"{platform.system()} {platform.release()}"


def architecture() -> str:
    return platform.machine() or os.environ.get("PROCESSOR_ARCHITECTURE", "unknown")


def hostname() -> str:
    return platform.node() or os.environ.get("COMPUTERNAME", "PC")


def agent_version() -> str:
    return __version__


def uptime_seconds() -> Optional[float]:
    """Seconds since boot (None when unavailable)."""
    try:
        boot_time = psutil.boot_time()
        if boot_time <= 0:
            return None
        return max(0.0, round(time.time() - boot_time, 1))
    except Exception:  # pragma: no cover - psutil edge cases
        return None


def system_summary() -> dict[str, Any]:
    """Static system information used at registration time."""
    memory = psutil.virtual_memory()
    disk = None
    try:
        usage = psutil.disk_usage(os.environ.get("SystemDrive", "C:\\") + "\\" if sys.platform == "win32" else "/")
        disk = round(usage.total / (1024**3), 1)
    except Exception:
        disk = None
    return {
        "os": os_name(),
        "architecture": architecture(),
        "hostname": hostname(),
        "platform": sys.platform,
        "agentVersion": agent_version(),
        "ramTotalMB": round(memory.total / (1024**2), 1),
        "diskTotalGB": disk,
        "cpuModel": _cpu_model(),
        "gpuModel": primary_gpu_name(),
    }


def _cpu_model() -> str:
    try:
        if sys.platform == "win32":
            import winreg

            key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:  # type: ignore[attr-defined]
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()  # type: ignore[attr-defined]
        return platform.processor() or platform.machine()
    except Exception:
        return platform.processor() or platform.machine() or "Unknown CPU"


def primary_gpu_name() -> Optional[str]:
    """Best-effort GPU model name (used on the device card)."""
    from src.gpu import gpu_summary

    summary = gpu_summary()
    return summary.get("model")
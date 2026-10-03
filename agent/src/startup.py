"""Windows startup management.

Autostart is a **normal, visible** mechanism: a value under

``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``

which the user can see and change in Task Manager -> Startup apps.  Nothing
here is hidden, and the agent is never registered as a service, driver or
scheduled task.

Startup is **enabled by default** - the first run registers the autostart entry
so the machine keeps reporting after a reboot.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from src.logger import get_logger

logger = get_logger()

APP_NAME = "PC-Monitor"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def executable_path() -> str:
    """Path used for the autostart entry (the EXE, or Python during development)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(sys.executable)


def _run_command() -> str:
    """Command line written to the Run key."""
    if getattr(sys, "frozen", False):
        return f'"{executable_path()}"'
    # Development: start the module silently with the interpreter that runs it.
    return f'"{executable_path()}" -m src.main'


def enable() -> bool:
    """Create/update the autostart entry. Returns ``True`` on success."""
    if sys.platform != "win32":
        logger.info("startup_unsupported", "autostart registry entry only applies on Windows")
        return False
    try:
        import winreg

        command = _run_command()
        with winreg.CreateKeyEx(  # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,  # type: ignore[attr-defined]
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)  # type: ignore[attr-defined]
        logger.info("startup_enabled", "agent will start with Windows", command=command)
        return True
    except Exception as exc:  # pragma: no cover - registry unavailable
        logger.error("startup_enable_failed", "could not enable startup", error=str(exc))
        return False


def disable() -> bool:
    """Remove the autostart entry. Returns ``True`` when it is gone."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,  # type: ignore[attr-defined]
        ) as key:
            winreg.DeleteValue(key, APP_NAME)  # type: ignore[attr-defined]
        logger.info("startup_disabled", "agent will no longer start with Windows")
        return True
    except FileNotFoundError:
        logger.info("startup_absent", "no startup entry present")
        return True
    except Exception as exc:  # pragma: no cover
        logger.error("startup_disable_failed", "could not disable startup", error=str(exc))
        return False


def is_enabled() -> bool:
    """Whether the autostart entry currently exists."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
            RUN_KEY,
            0,
            winreg.KEY_READ,  # type: ignore[attr-defined]
        ) as key:
            winreg.QueryValueEx(key, APP_NAME)  # type: ignore[attr-defined]
        return True
    except FileNotFoundError:
        return False
    except Exception:  # pragma: no cover
        return False


def startup_command() -> Optional[str]:
    """The current Run value (for ``--status``)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
            RUN_KEY,
            0,
            winreg.KEY_READ,  # type: ignore[attr-defined]
        ) as key:
            return str(winreg.QueryValueEx(key, APP_NAME)[0])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        return None


def apply_preference(enabled: bool) -> bool:
    """Enable or disable autostart based on the requested preference."""
    if enabled:
        return enable()
    return disable()


def configure(config: object) -> None:
    """Make the OS match the configured preference (called at startup)."""
    desired = bool(getattr(config, "startup_enabled", True))
    current = is_enabled()
    if desired and not current:
        if enable():
            logger.info("startup_applied", "autostart enabled at first run")
    elif not desired and current:
        disable()
        logger.info("startup_applied", "autostart disabled per configuration")


def note_first_run_hint() -> None:
    """Tell the user how startup works (no silent, invisible behaviour)."""
    logger.info(
        "startup_behaviour",
        "PC Monitor runs in the background and starts automatically with Windows "
        "(visible in Task Manager > Startup apps; disable with --no-startup)",
    )


def environment_summary() -> dict[str, object]:
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": str(executable_path()),
        "startupEnabled": is_enabled(),
        "startupCommand": startup_command(),
        "workingDirectory": os.getcwd(),
    }
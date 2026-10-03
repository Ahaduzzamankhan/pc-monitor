"""PC Monitor agent entrypoint.

Runs as a **background service with no GUI and no console window**:

* The PyInstaller build uses a windowed (console-free) executable, so it looks
  like a normal background application in Task Manager.
* Startup happens automatically with Windows through the standard, visible
  ``HKCU\\...\\Run`` entry (see :mod:`src.startup`).
* One instance per machine (named mutex), graceful shutdown on logoff.

Telemetry loop: one sample every ``TELEMETRY_INTERVAL_SECONDS`` (default 30)
plus a heartbeat every 60 seconds.  No remote control surface exists - the
agent only reads hardware telemetry and uploads it.

CLI::

    PC-Monitor.exe                  # run in the background (default)
    PC-Monitor.exe --status         # print local configuration
    PC-Monitor.exe --interval 60    # override the sampling interval
    PC-Monitor.exe --api-url URL    # point at another backend
    PC-Monitor.exe --no-startup     # disable autostart and exit
    PC-Monitor.exe --enable-startup # (re)enable autostart and exit
    PC-Monitor.exe --once           # collect and upload a single sample
    PC-Monitor.exe --reset          # forget device id + token
"""

from __future__ import annotations

import argparse
import ctypes
import json
import signal
import sys
import threading
import time
from typing import Optional

from src import __version__
from src.api import DeviceRevoked, MonitorApi
from src.collector import collect, utc_now_iso
from src.config import AgentConfig
from src.device import DeviceState
from src.logger import configure_logging, get_logger
from src import startup as startup_module

MUTEX_NAME = r"Global\PC-Monitor-Agent-Singleton"
HEARTBEAT_INTERVAL_SECONDS = 60

logger = get_logger()


class SingleInstance:
    """Windows named mutex so only one agent runs per machine."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._name = name
        self._handle: Optional[int] = None

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        try:
            handle = ctypes.windll.kernel32.CreateMutexW(None, False, self._name)  # type: ignore[attr-defined]
            if not handle:  # pragma: no cover
                return True
            already_running = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
            self._handle = handle
            return not already_running
        except Exception:  # pragma: no cover - fall back to running anyway
            return True

    def release(self) -> None:
        if self._handle and sys.platform == "win32":  # pragma: no cover
            try:
                ctypes.windll.kernel32.CloseHandle(self._handle)  # type: ignore[attr-defined]
            except Exception:
                pass
        self._handle = None


class Agent:
    """The monitoring loop."""

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.load()
        self.api = MonitorApi(self.config.api_url, token=self.config.load_token())
        self.device = DeviceState(self.config, self.api)
        self.stop_event = threading.Event()

    # -- lifecycle ---------------------------------------------------------
    def shutdown(self, *_args) -> None:
        logger.info("shutdown_requested", "stopping the agent")
        self.stop_event.set()

    def ensure_registered(self) -> bool:
        """Register when we have no credentials yet."""
        if self.device.load_token():
            self.device.registered = True
            logger.info(
                "using_existing_registration",
                "stored device token found",
                deviceId=self.config.device_id,
            )
            return True
        if self.device.register():
            return True
        logger.error(
            "registration_incomplete",
            "no device token - retrying on the next cycle",
            apiUrl=self.config.api_url,
        )
        return False

    def effective_interval(self) -> int:
        if self.config.server_telemetry_interval:
            return int(self.config.server_telemetry_interval)
        return int(self.config.telemetry_interval_seconds)

    # -- work --------------------------------------------------------------
    def tick(self, measure_latency: bool = True) -> None:
        """One telemetry cycle plus a heartbeat when due."""
        try:
            sample = collect(self.device.device_id, self.config.api_url, measure_latency)
            result = self.api.send_telemetry(sample)
        except DeviceRevoked as exc:
            self.device.revoked = True
            self.device.log_revoked(exc)
            return

        if result.ok:
            logger.info(
                "telemetry_sent",
                "telemetry uploaded",
                deviceId=self.device.device_id,
                latencyMs=result.latency_ms,
            )
        else:
            logger.warning(
                "telemetry_failed",
                "telemetry upload failed - sample dropped (no unbounded queue)",
                status=result.status_code,
                error=result.error,
            )

    def flush_pending(self) -> None:
        """Send any samples queued while the backend was unreachable."""
        queued = self.api.pending.drain()
        for sample in queued:
            try:
                result = self.api.send_telemetry(sample)
            except DeviceRevoked:
                return
            if not result.ok:
                self.api.pending.put(sample)
                break

    def run_forever(self) -> int:
        """Main loop: heartbeat, telemetry, periodic config persistence."""
        startup_module.configure(self.config)
        logger.info(
            "agent_started",
            "PC Monitor agent started",
            version=__version__,
            deviceId=self.config.device_id or "(pending registration)",
            apiUrl=self.config.api_url,
            intervalSeconds=self.effective_interval(),
            startupEnabled=startup_module.is_enabled(),
        )
        startup_module.note_first_run_hint()

        registered = self.ensure_registered()
        next_heartbeat = time.monotonic()

        while not self.stop_event.is_set():
            if self.device.revoked:
                logger.error(
                    "agent_paused",
                    "uploads stopped - fix the registration (PC-Monitor.exe --reset) and start again",
                )
                return 2

            if not registered:
                registered = self.ensure_registered()
                if not registered:
                    self.stop_event.wait(min(60, self.effective_interval()))
                    continue

            now = time.monotonic()
            if now >= next_heartbeat:
                try:
                    self.device.heartbeat(utc_now_iso())
                except DeviceRevoked as exc:
                    self.device.revoked = True
                    self.device.log_revoked(exc)
                    return 2
                next_heartbeat = now + HEARTBEAT_INTERVAL_SECONDS

            self.flush_pending()
            self.tick()
            self.stop_event.wait(self.effective_interval())

        self.api.close()
        logger.info("agent_stopped", "PC Monitor agent stopped")
        return 0

    def run_once(self) -> int:
        """Collect and upload exactly one sample (used by ``--once``)."""
        self.ensure_registered()
        self.device.heartbeat(utc_now_iso())
        self.tick(measure_latency=True)
        self.api.close()
        return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="PC-Monitor",
        description="PC Monitor - hardware telemetry agent (monitoring only).",
    )
    parser.add_argument("--version", action="version", version=f"PC-Monitor agent {__version__}")
    parser.add_argument("--api-url", help="Backend base URL (overrides config/env)")
    parser.add_argument("--interval", type=int, help="Telemetry interval in seconds")
    parser.add_argument("--name", help="Device name shown in the dashboard")
    parser.add_argument("--enable-startup", action="store_true", help="Enable autostart and exit")
    parser.add_argument("--no-startup", action="store_true", help="Disable autostart and exit")
    parser.add_argument("--status", action="store_true", help="Print local configuration and exit")
    parser.add_argument("--once", action="store_true", help="Upload a single sample and exit")
    parser.add_argument("--reset", action="store_true", help="Forget device id and token, then exit")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    return parser


def apply_overrides(config: AgentConfig, args: argparse.Namespace) -> AgentConfig:
    changed = False
    if args.api_url:
        config.api_url = args.api_url.rstrip("/")
        changed = True
    if args.interval:
        from src.config import _clamp_interval

        config.telemetry_interval_seconds = _clamp_interval(args.interval)
        changed = True
    if args.name:
        config.device_name = args.name
        changed = True
    if args.no_startup:
        config.startup_enabled = False
        changed = True
    if changed:
        config.save()
    return config


def print_status(config: AgentConfig) -> None:
    from src import startup as startup_info

    payload = {
        "version": __version__,
        "deviceId": config.device_id or None,
        "deviceName": config.device_name,
        "apiUrl": config.api_url,
        "telemetryIntervalSeconds": config.telemetry_interval_seconds,
        "heartbeatIntervalSeconds": config.heartbeat_interval_seconds,
        "registered": bool(config.load_token()),
        "configPath": str(config.config_path),
        "logPath": str(config.directory / "logs" / "agent.log"),
        **startup_info.environment_summary(),
    }
    print(json.dumps(payload, indent=2))


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Background service: no console output unless a console already exists
    # (i.e. the user ran it from a terminal or used --status/--once).
    configure_logging(args.log_level, console=sys.stderr is not None)
    logger.info(
        "agent_boot",
        "PC Monitor agent starting",
        version=__version__,
        args=[item for item in (argv or sys.argv[1:])],
    )

    config = AgentConfig.load()
    config = apply_overrides(config, args)

    if args.status:
        print_status(config)
        return 0
    if args.reset:
        config.clear_token()
        config.device_id = ""
        config.registered = False
        config.save()
        print("Local registration removed. The next start registers a new device.")
        return 0
    if args.enable_startup:
        return 0 if startup_module.enable() else 1
    if args.no_startup:
        return 0 if startup_module.disable() else 1

    instance = SingleInstance()
    if not instance.acquire():
        logger.info("already_running", "another PC Monitor agent is already running")
        return 0

    agent = Agent(config)
    signal.signal(signal.SIGINT, agent.shutdown)
    signal.signal(signal.SIGTERM, agent.shutdown)
    try:
        if args.once:
            return agent.run_once()
        return agent.run_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        agent.shutdown()
        return 0
    finally:
        agent.api.close()
        instance.release()


if __name__ == "__main__":
    raise SystemExit(main())
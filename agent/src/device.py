"""Device identity, registration and lifecycle.

First run:
1. mint a device id (``PC-XXXXXXXX``, random suffix),
2. collect hardware facts,
3. register with the backend,
4. store the returned token locally (DPAPI-protected on Windows).

If the backend reports the device as already registered, the agent stops and
explains how to recover instead of silently taking over an existing device.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any, Optional

from src import __version__
from src.api import DeviceRevoked, MonitorApi
from src.config import AgentConfig
from src.logger import get_logger
from src.system import system_summary

logger = get_logger()


def generate_device_id() -> str:
    """Mint a random device id (``PC-`` + 8 hex characters)."""
    return f"PC-{secrets.token_hex(4).upper()}"


def ensure_device_id(config: AgentConfig) -> str:
    """Return the stored device id, creating and persisting one when missing."""
    if not config.device_id:
        config.device_id = generate_device_id()
        logger.info("device_id_created", "new device id generated", deviceId=config.device_id)
        config.save()
    return config.device_id


def registration_payload(config: AgentConfig) -> dict[str, Any]:
    """Hardware facts sent to ``POST /api/devices/register``."""
    summary = system_summary()
    return {
        "deviceId": ensure_device_id(config),
        "name": config.device_name,
        "agentVersion": __version__,
        "os": summary["os"],
        "architecture": summary["architecture"],
        "hostname": summary["hostname"],
        "platform": summary["platform"],
        "cpuModel": summary["cpuModel"],
        "gpuModel": summary["gpuModel"],
        "ramTotalMB": summary["ramTotalMB"],
        "diskTotalGB": summary["diskTotalGB"],
        "telemetryIntervalSeconds": config.telemetry_interval_seconds,
    }


class DeviceState:
    """Registration + token lifecycle for this PC."""

    def __init__(self, config: AgentConfig, api: MonitorApi) -> None:
        self.config = config
        self.api = api
        self.registered = False
        self.revoked = False

    @property
    def device_id(self) -> str:
        return ensure_device_id(self.config)

    def load_token(self) -> str:
        token = self.config.load_token()
        if token:
            self.api.set_token(token)
        return token

    def register(self) -> bool:
        """Register the device (first run or explicit re-registration)."""
        payload = registration_payload(self.config)
        existing_token = self.load_token() or None
        logger.info(
            "registering",
            "registering with the backend",
            deviceId=payload["deviceId"],
            apiUrl=self.api.base_url,
            hasToken=bool(existing_token),
        )
        try:
            result = self.api.register(payload, token=existing_token)
        except DeviceRevoked as exc:
            self.revoked = True
            if exc.explicitly_revoked:
                logger.error(
                    "registration_rejected",
                    "this device was removed on the dashboard - re-register with: PC-Monitor.exe --reset",
                    error=str(exc),
                )
            else:
                logger.error(
                    "registration_rejected",
                    "backend does not recognise this device - re-register with: PC-Monitor.exe --reset",
                    error=str(exc),
                )
            return False

        if not result.ok or not result.data:
            logger.error(
                "registration_failed",
                "could not register",
                status=result.status_code,
                error=result.error,
            )
            return False

        token = str(result.data.get("token") or "")
        if not token:
            logger.error("registration_failed", "backend did not return a device token")
            return False

        self.config.device_id = str(result.data.get("deviceId") or payload["deviceId"])
        self.config.registered = True
        self.api.set_token(token)
        self.config.save_token(token)
        self.config.save()

        interval = result.data.get("telemetryIntervalSeconds")
        if interval:
            self.config.server_telemetry_interval = int(interval)
        self.registered = True
        logger.info(
            "registered",
            "device registered successfully",
            deviceId=self.config.device_id,
            created=bool(result.data.get("created")),
            latencyMs=result.latency_ms,
        )
        return True

    def heartbeat(self, timestamp: str) -> bool:
        """Send one heartbeat; ``False`` when the backend is unreachable."""
        try:
            result = self.api.heartbeat(self.device_id, timestamp, __version__)
        except DeviceRevoked as exc:
            self.revoked = True
            self.log_revoked(exc)
            return False
        if not result.ok:
            logger.warning("heartbeat_failed", "heartbeat not acknowledged", error=result.error)
            return False
        interval = (result.data or {}).get("telemetryIntervalSeconds")
        if interval:
            self.config.server_telemetry_interval = int(interval)
        return True

    def log_revoked(self, exc: DeviceRevoked) -> None:
        """Explain *why* uploads stopped, with the exact recovery step."""
        if exc.explicitly_revoked:
            logger.error(
                "device_revoked",
                "device was removed on the dashboard; its token is revoked. "
                "Re-register by running: PC-Monitor.exe --reset",
                error=str(exc),
            )
        else:
            logger.error(
                "device_unknown",
                "backend does not know this device (401). If it was never removed, the "
                "backend database may have been reset. Re-register with: PC-Monitor.exe --reset",
                error=str(exc),
            )

    def unregister_local(self) -> None:
        """Forget local credentials (used by ``--reset``)."""
        self.config.clear_token()
        self.config.device_id = ""
        self.config.registered = False
        self.config.save()
        logger.info("local_state_cleared", "device id and token removed")


def machine_fingerprint() -> str:
    """Stable, non-identifying machine marker used only for local locking."""
    return uuid.getnode().to_bytes(8, "big").hex()
"""Device lifecycle: registration, authentication, heartbeat, settings, removal."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from app.core.config import Settings, get_settings
from app.core.firebase import BaseStore, get_store
from app.core.security import (
    generate_device_token,
    hash_device_token,
    token_fingerprint,
    verify_device_token,
)
from app.models.device import (
    DeviceDetailResponse,
    DeviceListResponse,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    DeviceSettingsUpdate,
    DeviceSummary,
    HeartbeatResponse,
    LogEntry,
    TelemetrySummary,
)
from app.utils.logging import get_logger
from app.utils.time import from_iso, to_iso, utcnow
from app.utils.validation import conflict, forbidden, not_found, unauthorized

logger = get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 60
#: Routine telemetry/heartbeat log lines are throttled to keep Firestore writes low.
HEARTBEAT_LOG_INTERVAL_SECONDS = 600
TELEMETRY_LOG_INTERVAL_SECONDS = 300

TELEMETRY_SUMMARY_FIELDS = (
    "cpuUsage",
    "gpuUsage",
    "ramUsage",
    "cpuTemperature",
    "gpuTemperature",
    "diskUsage",
    "downloadMbps",
    "uploadMbps",
    "batteryPercent",
)

SENSORS = (
    "cpuTemperature",
    "gpuTemperature",
    "gpuUsage",
    "batteryPercent",
    "diskReadMbps",
    "cpuFrequencyMHz",
)


class DeviceService:
    def __init__(
        self,
        store: Optional[BaseStore] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._store = store or get_store()
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Authentication helpers
    # ------------------------------------------------------------------
    def authenticate_device(self, device_id: str, token: Optional[str]) -> dict[str, Any]:
        """Resolve a device from its id + token or raise 401/403."""
        device = self._store.get_device(device_id)
        if device is None:
            if self._store.is_revoked(device_id):
                raise forbidden(
                    "device_revoked",
                    "this device was removed; install the agent again to re-register",
                )
            raise unauthorized("invalid_credentials", "unknown device or invalid token")
        if not verify_device_token(token or "", device.get("tokenHash", ""), self._settings):
            raise unauthorized("invalid_token", "device token is not valid")
        return device

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_device(
        self, payload: DeviceRegisterRequest, token: Optional[str] = None
    ) -> DeviceRegisterResponse:
        device_id = payload.deviceId
        existing = self._store.get_device(device_id)

        if existing is not None:
            # Re-registering a known device requires proof of the current token.
            if not verify_device_token(token or "", existing.get("tokenHash", ""), self._settings):
                raise conflict(
                    "device_already_registered",
                    "device id is already registered; remove it from the dashboard to re-register",
                )
            new_token = generate_device_token()
            updated = self._store.update_device(
                device_id,
                {
                    "tokenHash": hash_device_token(new_token, self._settings),
                    "tokenFingerprint": token_fingerprint(new_token),
                    "agentVersion": payload.agentVersion,
                    "lastSeen": to_iso(utcnow()),
                    "online": True,
                    "updatedAt": to_iso(utcnow()),
                    **self._hardware_fields(payload),
                },
            ) or existing
            self._log(
                device_id,
                "device_reregistered",
                f"{updated.get('name')} re-registered with agent {payload.agentVersion}",
                {"agentVersion": payload.agentVersion},
            )
            return self._register_response(updated, new_token, created=False)

        self._store.clear_revocation(device_id)
        new_token = generate_device_token()
        now = utcnow()
        device = {
            "deviceId": device_id,
            "name": payload.name,
            "agentVersion": payload.agentVersion,
            "os": payload.os,
            "architecture": payload.architecture,
            "hostname": payload.hostname,
            "platform": payload.platform,
            "cpuModel": payload.cpuModel,
            "gpuModel": payload.gpuModel,
            "ramTotalMB": payload.ramTotalMB,
            "diskTotalGB": payload.diskTotalGB,
            "telemetryIntervalSeconds": (
                payload.telemetryIntervalSeconds
                or self._settings.default_telemetry_interval_seconds
            ),
            "startupEnabled": False,
            "online": True,
            "createdAt": to_iso(now),
            "updatedAt": to_iso(now),
            "lastSeen": to_iso(now),
            "tokenHash": hash_device_token(new_token, self._settings),
            "tokenFingerprint": token_fingerprint(new_token),
            "telemetryCount": 0,
        }
        created = self._store.create_device(device)
        self._log(
            device_id,
            "device_registered",
            f"{device['name']} registered",
            {"agentVersion": device["agentVersion"], "os": device["os"]},
        )
        logger.info(
            "device_registered",
            "new device registered",
            deviceId=device_id,
            agentVersion=device["agentVersion"],
        )
        return self._register_response(created, new_token, created=True)

    @staticmethod
    def _hardware_fields(payload: DeviceRegisterRequest) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "os": payload.os,
            "architecture": payload.architecture,
            "hostname": payload.hostname,
            "platform": payload.platform,
            "cpuModel": payload.cpuModel,
            "gpuModel": payload.gpuModel,
            "ramTotalMB": payload.ramTotalMB,
            "diskTotalGB": payload.diskTotalGB,
        }
        if payload.telemetryIntervalSeconds is not None:
            fields["telemetryIntervalSeconds"] = payload.telemetryIntervalSeconds
        return fields

    def _register_response(
        self, device: dict[str, Any], token: str, *, created: bool
    ) -> DeviceRegisterResponse:
        return DeviceRegisterResponse(
            deviceId=device["deviceId"],
            token=token,
            created=created,
            heartbeatIntervalSeconds=HEARTBEAT_INTERVAL_SECONDS,
            telemetryIntervalSeconds=int(
                device.get("telemetryIntervalSeconds")
                or self._settings.default_telemetry_interval_seconds
            ),
            retentionDays=self._settings.telemetry_retention_days,
            serverTime=utcnow(),
        )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------
    def record_heartbeat(
        self, device_id: str, token: Optional[str], agent_version: str
    ) -> HeartbeatResponse:
        device = self.authenticate_device(device_id, token)
        now = utcnow()
        last_seen = from_iso(device.get("lastSeen"))
        was_online = self._is_online(device)
        patch: dict[str, Any] = {
            "lastSeen": to_iso(now),
            "online": True,
            "agentVersion": agent_version,
            "updatedAt": to_iso(now),
        }

        if not was_online:
            offline_for = (now - last_seen).total_seconds() if last_seen else None
            self._log(
                device_id,
                "agent_reconnected",
                f"{device.get('name')} reconnected",
                {"offlineForSeconds": round(offline_for, 1) if offline_for else None},
            )
        elif self._should_log(device, "lastHeartbeatLogAt", HEARTBEAT_LOG_INTERVAL_SECONDS):
            self._log(
                device_id,
                "heartbeat_received",
                f"Heartbeat from {device.get('name')}",
                {"agentVersion": agent_version},
                patch=patch,
            )
        self._store.update_device(device_id, patch)

        return HeartbeatResponse(
            deviceId=device_id,
            acknowledged=True,
            serverTime=now,
            nextHeartbeatSeconds=HEARTBEAT_INTERVAL_SECONDS,
            telemetryIntervalSeconds=int(
                device.get("telemetryIntervalSeconds")
                or self._settings.default_telemetry_interval_seconds
            ),
            status="online",
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def _is_online(self, device: dict[str, Any]) -> bool:
        last_seen = from_iso(device.get("lastSeen"))
        if last_seen is None:
            return False
        return (utcnow() - last_seen) <= timedelta(
            seconds=self._settings.online_threshold_seconds
        )

    @staticmethod
    def _summary_from_sample(sample: Optional[dict[str, Any]]) -> Optional[TelemetrySummary]:
        if not sample:
            return None
        data = {"timestamp": from_iso(sample.get("timestamp"))}
        data.update({field: sample.get(field) for field in TELEMETRY_SUMMARY_FIELDS})
        return TelemetrySummary(**data)

    @staticmethod
    def _to_summary(
        device: dict[str, Any], sample: Optional[dict[str, Any]], online: bool
    ) -> DeviceSummary:
        last_seen = from_iso(device.get("lastSeen"))
        return DeviceSummary(
            deviceId=device["deviceId"],
            name=device.get("name") or device["deviceId"],
            online=online,
            status="online" if online else "offline",
            lastSeen=last_seen,
            secondsSinceLastSeen=(
                round((utcnow() - last_seen).total_seconds(), 1) if last_seen else None
            ),
            createdAt=from_iso(device.get("createdAt")),
            agentVersion=device.get("agentVersion"),
            os=device.get("os"),
            architecture=device.get("architecture"),
            hostname=device.get("hostname"),
            cpuModel=device.get("cpuModel"),
            gpuModel=device.get("gpuModel"),
            ramTotalMB=device.get("ramTotalMB"),
            diskTotalGB=device.get("diskTotalGB"),
            telemetryIntervalSeconds=device.get("telemetryIntervalSeconds"),
            startupEnabled=device.get("startupEnabled"),
            metrics=DeviceService._summary_from_sample(sample),
        )

    @staticmethod
    def _is_online_static(
        device: dict[str, Any], last_seen: Optional[Any], threshold: int = 120
    ) -> bool:
        if last_seen is None:
            return False
        return (utcnow() - last_seen) <= timedelta(seconds=threshold)

    def list_devices(self) -> DeviceListResponse:
        devices = self._store.list_devices()
        device_ids = [device["deviceId"] for device in devices]
        samples = self._store.latest_telemetry_batch(device_ids) if device_ids else {}

        summaries = [
            self._to_summary(device, samples.get(device["deviceId"]), self._is_online(device))
            for device in devices
        ]

        summaries.sort(key=lambda item: (not item.online, item.name.lower()))
        return DeviceListResponse(
            devices=summaries,
            count=len(summaries),
            onlineCount=sum(1 for item in summaries if item.online),
            generatedAt=utcnow(),
            refreshAfterSeconds=15,
        )

    def get_device(self, device_id: str) -> DeviceDetailResponse:
        device = self._store.get_device(device_id)
        if device is None:
            raise not_found("device_not_found", f"unknown device {device_id}")
        sample = self._store.latest_telemetry(device_id)
        summary = self._to_summary(device, sample, self._is_online(device))
        logs = [
            LogEntry(**{**entry, "timestamp": from_iso(entry.get("timestamp"))})
            for entry in self._store.list_logs(device_id, limit=25)
        ]
        return DeviceDetailResponse(
            **summary.model_dump(),
            telemetryStored=self._store.count_telemetry(device_id),
            retentionDays=self._settings.telemetry_retention_days,
            retentionHours=self._settings.max_range_hours(),
            supportedRanges=self._settings.supported_ranges(),
            recentLogs=logs,
        )

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------
    def get_logs(
        self, device_id: Optional[str], limit: int = 100
    ) -> list[dict[str, Any]]:
        """Activity log entries (device existence is validated by the router)."""
        return self._store.list_logs(device_id, limit=limit)

    # ------------------------------------------------------------------
    # Settings / removal
    # ------------------------------------------------------------------
    def update_settings(self, device_id: str, update: DeviceSettingsUpdate) -> DeviceSummary:
        device = self._store.get_device(device_id)
        if device is None:
            raise not_found("device_not_found", f"unknown device {device_id}")
        device_id = device["deviceId"]
        patch: dict[str, Any] = {"updatedAt": to_iso(utcnow())}
        if update.name is not None:
            patch["name"] = update.name
        if update.telemetryIntervalSeconds is not None:
            patch["telemetryIntervalSeconds"] = update.telemetryIntervalSeconds
        if update.startupEnabled is not None:
            patch["startupEnabled"] = update.startupEnabled
        self._store.update_device(device_id, patch)
        self._log(
            device_id,
            "device_settings_updated",
            f"Settings updated for {device_id}",
            {"fields": sorted(update.model_dump(exclude_none=True))},
        )
        return self._to_summary(
            self._store.get_device(device_id) or device, None, self._is_online(device)
        )

    def delete_device(self, device_id: str) -> dict[str, Any]:
        device = self._store.get_device(device_id)
        if device is None:
            raise not_found("device_not_found", f"unknown device {device_id}")
        telemetry_count = self._store.count_telemetry(device_id)
        deleted = self._store.delete_device(device_id)
        # Deleting the document removes the token hash, so any agent still
        # holding the old token receives 401/403 and must re-register.
        self._store.record_revocation(device_id, "removed_by_user", utcnow())
        logger.warning(
            "device_removed",
            "device removed and token revoked",
            deviceId=device_id,
            deletedTelemetry=telemetry_count,
        )
        self._store.append_log(
            device_id,
            "device_removed",
            level="warning",
            message=f"{device.get('name')} was removed from the dashboard",
            data={"telemetryDeleted": telemetry_count},
        )
        return {
            "deviceId": device_id,
            "deleted": deleted,
            "tokenRevoked": True,
            "deletedTelemetry": telemetry_count,
            "message": "Device removed; its token is revoked and telemetry purged.",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _log(
        self,
        device_id: str,
        event: str,
        message: str = "",
        data: Optional[dict[str, Any]] = None,
        *,
        patch: Optional[dict[str, Any]] = None,
    ) -> None:
        if patch:
            self._store.update_device(device_id, patch)
        self._store.append_log(device_id, event, message=message, data=data or {})

    def _should_log(self, device: dict[str, Any], field: str, interval_seconds: int) -> bool:
        last = from_iso(device.get(field))
        if last is None:
            return True
        return (utcnow() - last) >= timedelta(seconds=interval_seconds)

    def mark_offline_devices(self) -> list[str]:
        """Flip stale devices to offline and log the transition once."""
        threshold = self._settings.online_threshold_seconds
        changed: list[str] = []
        for device in self._store.list_devices():
            last_seen = from_iso(device.get("lastSeen"))
            if last_seen is None:
                continue
            stale_for = (utcnow() - last_seen).total_seconds()
            if stale_for > threshold and device.get("online"):
                self._store.update_device(
                    device["deviceId"],
                    {"online": False, "updatedAt": to_iso(utcnow())},
                )
                self._store.append_log(
                    device["deviceId"],
                    "agent_disconnected",
                    level="warning",
                    message=f"{device.get('name')} stopped reporting",
                    data={"lastSeen": to_iso(last_seen), "offlineForSeconds": round(stale_for, 1)},
                )
                changed.append(device["deviceId"])
            elif stale_for <= threshold and not device.get("online"):
                self._store.update_device(device["deviceId"], {"online": True})
        return changed


_device_service: Optional[DeviceService] = None


def get_device_service() -> DeviceService:
    global _device_service
    if _device_service is None:
        _device_service = DeviceService()
    return _device_service


def reset_device_service() -> None:
    """Test helper - drops the cached service so it picks up a new store."""
    global _device_service
    _device_service = None
"""Telemetry ingestion and history queries.

Retention is enforced in three independent places:

1. Every stored sample carries ``expiresAt`` so Firestore TTL can remove it.
2. Ingestion rejects samples older than the retention window or too far in the
   future, so expired history can never be (re)created.
3. The scheduled cleanup service deletes anything that slipped through.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.config import Settings, get_settings
from app.core.firebase import BaseStore, get_store
from app.models.telemetry import (
    TelemetryPayload,
    TelemetryPoint,
    TelemetryResponse,
    TelemetrySeriesResponse,
)
from app.utils.logging import get_logger
from app.utils.time import from_iso, to_iso, utcnow
from app.utils.validation import (
    ensure_finite_numbers,
    is_within_retention,
    not_found,
    validate_range,
)

logger = get_logger(__name__)

TELEMETRY_LOG_INTERVAL_SECONDS = 300

NUMERIC_FIELDS = (
    "cpuUsage",
    "cpuFrequencyMHz",
    "cpuTemperature",
    "gpuUsage",
    "gpuTemperature",
    "vramUsedMB",
    "vramTotalMB",
    "ramUsage",
    "ramUsedMB",
    "ramTotalMB",
    "ramAvailableMB",
    "diskUsage",
    "diskTotalGB",
    "diskUsedGB",
    "diskFreeGB",
    "diskReadMbps",
    "diskWriteMbps",
    "downloadMbps",
    "uploadMbps",
    "apiLatencyMs",
    "batteryPercent",
    "batteryTimeLeftSeconds",
    "uptimeSeconds",
)

SENSORS = ("cpuTemperature", "gpuTemperature", "gpuUsage", "batteryPercent")


class TelemetryService:
    def __init__(
        self,
        store: Optional[BaseStore] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._store = store or get_store()
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def ingest(self, device: dict[str, Any], payload: TelemetryPayload) -> TelemetryResponse:
        device_id = device["deviceId"]
        received_at = utcnow()
        sample_time = from_iso(payload.timestamp)
        is_within_retention(
            sample_time,
            self._settings.retention_seconds,
            self._settings.max_future_clock_skew_seconds,
        )

        document: dict[str, Any] = payload.model_dump(exclude_none=False)
        document = {key: value for key, value in document.items() if value is not None}
        ensure_finite_numbers(document, NUMERIC_FIELDS)
        document["deviceId"] = device_id
        document["timestamp"] = to_iso(sample_time)
        document["receivedAt"] = to_iso(received_at)
        # TTL anchor: the sample disappears exactly retention_days later.
        document["expiresAt"] = to_iso(
            sample_time + timedelta(seconds=self._settings.retention_seconds)
        )
        if payload.cpuPerCore is not None:
            document["cpuPerCore"] = [
                round(float(value), 2) if value is not None else None
                for value in payload.cpuPerCore
            ]

        telemetry_id = self._store.append_telemetry(device_id, document)
        patch: dict[str, Any] = {
            "lastSeen": to_iso(received_at),
            "online": True,
            "updatedAt": to_iso(received_at),
            "telemetryCount": int(device.get("telemetryCount") or 0) + 1,
        }
        if payload.ramTotalMB and not device.get("ramTotalMB"):
            patch["ramTotalMB"] = payload.ramTotalMB

        sensor_state = self._sensor_state(document)
        previous_state = device.get("sensorState")
        self._store.update_device(device_id, patch)

        if previous_state != sensor_state:
            patch["sensorState"] = sensor_state
            self._store.update_device(device_id, patch)
            unavailable = [name for name in SENSORS if document.get(name) is None]
            if unavailable:
                self._store.append_log(
                    device_id,
                    "sensor_unavailable",
                    level="warning",
                    message=f"Sensors unavailable: {', '.join(unavailable)}",
                    data={"sensors": unavailable},
                )
            else:
                self._store.append_log(
                    device_id,
                    "sensor_recovered",
                    message="All monitored sensors are reporting",
                    data={"sensors": list(SENSORS)},
                )

        if self._should_log_telemetry(device):
            self._store.append_log(
                device_id,
                "telemetry_received",
                message=f"Telemetry sample stored for {device.get('name')}",
                data={
                    "cpuUsage": document.get("cpuUsage"),
                    "ramUsage": document.get("ramUsage"),
                    "gpuUsage": document.get("gpuUsage"),
                },
            )
            self._store.update_device(
                device_id, {"lastTelemetryLogAt": to_iso(received_at)}
            )

        return TelemetryResponse(
            deviceId=device_id,
            telemetryId=telemetry_id,
            receivedAt=received_at,
            expiresAt=from_iso(document["expiresAt"]),
            retentionDays=self._settings.telemetry_retention_days,
        )

    @staticmethod
    def _sensor_state(document: dict[str, Any]) -> dict[str, bool]:
        return {name: document.get(name) is not None for name in SENSORS}

    def _should_log_telemetry(self, device: dict[str, Any]) -> bool:
        last = from_iso(device.get("lastTelemetryLogAt"))
        if last is None:
            return True
        return (utcnow() - last) >= timedelta(seconds=TELEMETRY_LOG_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def get_series(
        self, device_id: str, range_label: Optional[str] = None
    ) -> TelemetrySeriesResponse:
        device = self._store.get_device(device_id)
        if device is None:
            raise not_found("device_not_found", f"unknown device {device_id}")

        label, hours = validate_range(
            range_label, max_hours=self._settings.max_range_hours()
        )
        end = utcnow()
        start = end - timedelta(hours=hours)
        max_points = self._settings.max_telemetry_points
        raw = self._store.list_telemetry(device_id, start, end, max_points)
        truncated = len(raw) >= max_points

        resolution = max(1, round(hours * 3600 / max_points))
        points = self._downsample(raw, start, resolution)

        return TelemetrySeriesResponse(
            deviceId=device_id,
            range=label,
            rangeHours=hours,
            startTime=start,
            endTime=end,
            resolutionSeconds=resolution,
            count=len(points),
            empty=len(points) == 0,
            truncated=truncated,
            maxPoints=max_points,
            retentionDays=self._settings.telemetry_retention_days,
            points=points,
        )

    @staticmethod
    def _downsample(
        rows: list[dict[str, Any]], start: datetime, resolution_seconds: int
    ) -> list[TelemetryPoint]:
        """Average samples into fixed buckets so charts stay smooth and small."""
        buckets: dict[int, dict[str, list[float]]] = {}
        timestamps: dict[int, str] = {}
        for row in rows:
            timestamp = row.get("timestamp")
            if not timestamp:
                continue
            offset = from_iso(timestamp) - start
            index = max(0, int(offset.total_seconds() // resolution_seconds))
            timestamps.setdefault(index, timestamp)
            for field in TelemetryPoint.model_fields:
                if field == "timestamp":
                    continue
                value = row.get(field)
                if isinstance(value, (int, float)):
                    buckets.setdefault(index, {}).setdefault(field, []).append(float(value))

        points: list[TelemetryPoint] = []
        for index in sorted(buckets):
            values = buckets[index]
            points.append(
                TelemetryPoint(
                    timestamp=from_iso(timestamps[index]),
                    **{
                        field: round(sum(samples) / len(samples), 2)
                        for field, samples in values.items()
                    },
                )
            )
        return points

    def latest(self, device_id: str) -> Optional[dict[str, Any]]:
        return self._store.latest_telemetry(device_id)


_telemetry_service: Optional[TelemetryService] = None


def get_telemetry_service() -> TelemetryService:
    global _telemetry_service
    if _telemetry_service is None:
        _telemetry_service = TelemetryService()
    return _telemetry_service


def reset_telemetry_service() -> None:
    global _telemetry_service
    _telemetry_service = None
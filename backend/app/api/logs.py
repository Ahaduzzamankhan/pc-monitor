"""Aggregate activity log across all devices (dashboard /logs page)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import _settings_dependency
from app.models.device import DeviceSummary, LogEntry, LogListResponse
from app.services.device_service import DeviceService, get_device_service
from app.utils.time import from_iso, utcnow

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get(
    "",
    response_model=LogListResponse,
    summary="Recent activity across all devices",
)
def list_logs(
    limit: int = Query(default=100, ge=1, le=500),
    device_id: Optional[str] = Query(default=None, alias="deviceId"),
    level: Optional[str] = Query(default=None, pattern="^(info|warning|error)$"),
    devices: DeviceService = Depends(get_device_service),
) -> LogListResponse:
    """Never exposes tokens or credentials - only event metadata."""
    target = device_id.upper() if device_id else None
    entries = devices.get_logs(target, limit=limit)
    names = {device.deviceId: device.name for device in devices.list_devices().devices}
    logs: list[LogEntry] = []
    for entry in entries:
        if level and entry.get("level", "info") != level:
            continue
        owner = entry.get("deviceId")
        logs.append(
            LogEntry(
                logId=entry.get("logId"),
                deviceId=owner,
                deviceName=names.get(owner),
                event=entry.get("event", "unknown"),
                level=entry.get("level", "info"),
                message=entry.get("message", ""),
                data=entry.get("data") or {},
                timestamp=from_iso(entry.get("timestamp")),
            )
        )
    return LogListResponse(logs=logs, count=len(logs), generatedAt=utcnow())
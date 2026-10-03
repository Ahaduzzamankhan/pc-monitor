"""Device endpoints: registration (agent) plus dashboard reads and management."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, status

from app.api.deps import _settings_dependency, device_token
from app.models.device import (
    DeleteDeviceResponse,
    DeviceDetailResponse,
    DeviceListResponse,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    DeviceSettingsUpdate,
    DeviceSummary,
    LogEntry,
    LogListResponse,
)
from app.services.device_service import DeviceService, get_device_service
from app.utils.logging import get_logger
from app.utils.time import from_iso, utcnow

logger = get_logger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.post(
    "/register",
    response_model=DeviceRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register the agent and receive a device token",
    responses={
        201: {"description": "Device registered"},
        400: {"description": "Invalid registration payload"},
        409: {"description": "Device id already registered"},
        429: {"description": "Rate limited"},
    },
)
def register_device(
    payload: DeviceRegisterRequest,
    token: str = Depends(device_token),
    devices: DeviceService = Depends(get_device_service),
) -> DeviceRegisterResponse:
    """First-run registration.

    The response contains the device token **once**.  It is stored hashed on the
    backend and the agent keeps it in its local configuration; it is never
    displayed in the dashboard.
    """
    return devices.register_device(payload, token or None)


@router.get(
    "",
    response_model=DeviceListResponse,
    summary="List every registered device",
)
def list_devices(
    devices: DeviceService = Depends(get_device_service),
) -> DeviceListResponse:
    """Automatic discovery: every registered PC appears here, no configuration."""
    return devices.list_devices()


@router.get(
    "/{device_id}",
    response_model=DeviceDetailResponse,
    summary="Device detail",
    responses={404: {"description": "Unknown device"}},
)
def get_device(
    device_id: str,
    devices: DeviceService = Depends(get_device_service),
) -> DeviceDetailResponse:
    return devices.get_device(device_id.upper())


@router.patch(
    "/{device_id}",
    response_model=DeviceSummary,
    summary="Update device settings (name, interval, startup preference)",
    responses={404: {"description": "Unknown device"}},
)
def update_device(
    device_id: str,
    update: DeviceSettingsUpdate = Body(...),
    devices: DeviceService = Depends(get_device_service),
) -> DeviceSummary:
    return devices.update_settings(device_id.upper(), update)


@router.delete(
    "/{device_id}",
    response_model=DeleteDeviceResponse,
    summary="Remove a device and revoke its token",
    responses={404: {"description": "Unknown device"}},
)
def delete_device(
    device_id: str,
    devices: DeviceService = Depends(get_device_service),
) -> DeleteDeviceResponse:
    """Removal is destructive for telemetry and revokes the agent token.

    A previously installed ``PC-Monitor.exe`` will receive 401/403 and must be
    registered again to come back.
    """
    return DeleteDeviceResponse(**devices.delete_device(device_id.upper()))


@router.get(
    "/{device_id}/logs",
    response_model=LogListResponse,
    summary="Activity log for a single device",
    responses={404: {"description": "Unknown device"}},
)
def device_logs(
    device_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    devices: DeviceService = Depends(get_device_service),
) -> LogListResponse:
    normalized = device_id.upper()
    entries = devices.get_logs(normalized, limit=limit)
    return LogListResponse(
        logs=[_to_log_entry(entry) for entry in entries],
        count=len(entries),
        generatedAt=utcnow(),
    )


def _to_log_entry(entry: dict) -> LogEntry:
    return LogEntry(
        logId=entry.get("logId"),
        deviceId=entry.get("deviceId"),
        deviceName=entry.get("deviceName"),
        event=entry.get("event", "unknown"),
        level=entry.get("level", "info"),
        message=entry.get("message", ""),
        data=entry.get("data") or {},
        timestamp=from_iso(entry.get("timestamp")),
    )
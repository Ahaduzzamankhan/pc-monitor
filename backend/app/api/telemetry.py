"""Telemetry ingestion (agent) and history queries (dashboard)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, Query, status

from app.api.deps import _settings_dependency, device_token
from app.core.security import constant_time_equals
from app.models.common import CleanupStatusResponse
from app.models.telemetry import TelemetryPayload, TelemetryResponse, TelemetrySeriesResponse
from app.services.cleanup_service import CleanupService, get_cleanup_service
from app.services.device_service import DeviceService, get_device_service
from app.services.telemetry_service import TelemetryService, get_telemetry_service
from app.utils.logging import get_logger
from app.utils.validation import unauthorized, validate_device_id

logger = get_logger(__name__)

router = APIRouter(tags=["telemetry"])


@router.post(
    "/api/telemetry",
    response_model=TelemetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit one telemetry sample",
    responses={
        202: {"description": "Sample stored"},
        400: {"description": "Sample outside the retention window or invalid"},
        401: {"description": "Invalid device token"},
        403: {"description": "Device token revoked"},
        413: {"description": "Payload too large"},
        422: {"description": "Validation failed (e.g. CPU above 100)"},
        429: {"description": "Rate limited"},
    },
)
def submit_telemetry(
    payload: TelemetryPayload = Body(...),
    token: str = Depends(device_token),
    devices: DeviceService = Depends(get_device_service),
    telemetry: TelemetryService = Depends(get_telemetry_service),
) -> TelemetryResponse:
    """Store one sample.

    The device id travels with the sample so a single agent process can be
    authenticated once per request without extra round trips.
    """
    device_id = validate_device_id(payload.deviceId)
    device = devices.authenticate_device(device_id, token)
    return telemetry.ingest(device, payload)


@router.get(
    "/api/devices/{device_id}/telemetry",
    response_model=TelemetrySeriesResponse,
    summary="Telemetry history for a device",
    responses={
        400: {"description": "Unsupported range or range beyond retention"},
        404: {"description": "Unknown device"},
    },
)
def device_telemetry(
    device_id: str,
    range: Optional[str] = Query(
        default="6h", description="One of 1h, 6h, 24h, 7d"
    ),
    telemetry: TelemetryService = Depends(get_telemetry_service),
) -> TelemetrySeriesResponse:
    """Only the window currently displayed is queried, and never more than 7d."""
    return telemetry.get_series(device_id.upper(), range)


@router.get(
    "/api/system/cleanup",
    response_model=CleanupStatusResponse,
    summary="Retention and cleanup status",
)
def cleanup_status(
    cleanup: CleanupService = Depends(get_cleanup_service),
) -> CleanupStatusResponse:
    """Exposes whether Firestore TTL is active and when cleanup last ran."""
    return CleanupStatusResponse(**cleanup.status)


@router.post(
    "/internal/cleanup",
    summary="Trigger a cleanup pass (scheduler / cron friendly)",
    include_in_schema=True,
)
async def trigger_cleanup(
    x_cleanup_token: Optional[str] = Header(default=None, alias="X-Cleanup-Token"),
    cleanup: CleanupService = Depends(get_cleanup_service),
    settings=Depends(_settings_dependency),
) -> dict:
    """Run one cleanup pass immediately.

    Guarded by ``CLEANUP_SECRET`` via the ``X-Cleanup-Token`` header.  Used by an
    external scheduler on platforms where long-lived background processes are not
    available (e.g. serverless deployments).  Only telemetry is ever deleted.
    """
    expected = settings.cleanup_secret.get_secret_value() if settings.cleanup_secret else None
    if not expected or not x_cleanup_token or not constant_time_equals(
        x_cleanup_token, expected
    ):
        raise unauthorized("invalid_cleanup_token", "invalid or missing X-Cleanup-Token")
    return await cleanup.run_locked()
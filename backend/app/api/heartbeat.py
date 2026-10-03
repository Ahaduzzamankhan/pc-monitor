"""Heartbeat endpoint (agent liveness)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import device_token
from app.models.device import HeartbeatRequest, HeartbeatResponse
from app.services.device_service import DeviceService, get_device_service
from app.utils.validation import validate_device_id

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    status_code=status.HTTP_200_OK,
    summary="Agent heartbeat",
    responses={
        200: {"description": "Heartbeat acknowledged"},
        401: {"description": "Invalid or revoked device token"},
        422: {"description": "Malformed heartbeat payload"},
        429: {"description": "Rate limited"},
    },
)
def heartbeat(
    payload: HeartbeatRequest,
    token: str = Depends(device_token),
    devices: DeviceService = Depends(get_device_service),
) -> HeartbeatResponse:
    """Refresh ``lastSeen``; the dashboard derives online status from it.

    A device is ONLINE while ``lastSeen`` is younger than
    ``ONLINE_THRESHOLD_SECONDS`` (default 120s).
    """
    device_id = validate_device_id(payload.deviceId)
    return devices.record_heartbeat(device_id, token, payload.agentVersion)
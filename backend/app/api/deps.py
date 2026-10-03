"""Shared FastAPI dependencies.

Authentication in PC Monitor is **device scoped**: every agent proves its
identity with the token issued at registration.  The dashboard itself is a
read-only view and is protected at the edge (see the README - Vercel
Deployment Protection or a private network), not with an in-app login.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, Header, Request

from app.core.config import Settings, get_settings
from app.services.device_service import DeviceService, get_device_service


def settings_dependency() -> Settings:
    return get_settings()


_settings_dependency = settings_dependency


def client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def device_token(
    authorization: Optional[str] = Header(default=None),
    x_device_token: Optional[str] = Header(default=None, alias="X-Device-Token"),
) -> str:
    """Extract the agent's device token from the request headers."""
    if x_device_token:
        return x_device_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def authenticated_device(
    device_id: str,
    token: str = Depends(device_token),
    devices: DeviceService = Depends(get_device_service),
) -> dict[str, Any]:
    """Resolve the device making an agent request (401/403 on failure)."""
    return devices.authenticate_device(device_id, token)
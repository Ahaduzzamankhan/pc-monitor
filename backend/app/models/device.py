"""Device models: registration, heartbeat and dashboard facing responses."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.validation import (
    MAX_DEVICE_NAME_LENGTH,
    MAX_MODEL_LENGTH,
    MAX_OS_LENGTH,
    CONTROL_CHARS,
)

DEVICE_ID_RE = re.compile(r"^PC-[A-F0-9]{6,24}$")


class StrictModel(BaseModel):
    """Rejects unknown keys so malformed agent payloads cannot slip through."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DeviceRegisterRequest(StrictModel):
    """Sent once by PC-Monitor.exe the first time it runs."""

    deviceId: str = Field(..., description="Device id, e.g. PC-7F42A91C")
    name: str = Field(..., min_length=1, max_length=MAX_DEVICE_NAME_LENGTH)
    agentVersion: str = Field(..., min_length=1, max_length=32)
    os: str = Field(..., min_length=1, max_length=MAX_OS_LENGTH)
    architecture: Optional[str] = Field(default=None, max_length=32)
    hostname: Optional[str] = Field(default=None, max_length=MAX_DEVICE_NAME_LENGTH)
    cpuModel: Optional[str] = Field(default=None, max_length=MAX_MODEL_LENGTH)
    gpuModel: Optional[str] = Field(default=None, max_length=MAX_MODEL_LENGTH)
    ramTotalMB: Optional[float] = Field(default=None, ge=0, le=1_048_576)
    diskTotalGB: Optional[float] = Field(default=None, ge=0, le=1_048_576)
    telemetryIntervalSeconds: Optional[int] = Field(default=None, ge=10, le=3600)
    platform: Optional[str] = Field(default=None, max_length=32)

    @field_validator("deviceId")
    @classmethod
    def _validate_device_id(cls, value: str) -> str:
        cleaned = (value or "").strip().upper()
        if not DEVICE_ID_RE.match(cleaned):
            raise ValueError("deviceId must look like PC-XXXXXXXX (uppercase hex)")
        return cleaned

    @field_validator("name", "os", "hostname", "architecture", "platform")
    @classmethod
    def _strip_control_chars(cls, value: Optional[str]) -> Optional[str]:
        return CONTROL_CHARS.sub("", value).strip() if value else value

    @field_validator("cpuModel", "gpuModel")
    @classmethod
    def _clean_model(cls, value: Optional[str]) -> Optional[str]:
        return CONTROL_CHARS.sub("", value).strip() if value else value


class DeviceRegisterResponse(BaseModel):
    deviceId: str
    token: str = Field(..., description="Issued once; never shown in the dashboard")
    created: bool
    heartbeatIntervalSeconds: int
    telemetryIntervalSeconds: int
    retentionDays: int
    serverTime: datetime


class HeartbeatRequest(StrictModel):
    """Periodic liveness signal; also refreshes the device's lastSeen."""

    deviceId: str
    timestamp: datetime
    agentVersion: str = Field(..., min_length=1, max_length=32)

    @field_validator("deviceId")
    @classmethod
    def _validate_device_id(cls, value: str) -> str:
        cleaned = (value or "").strip().upper()
        if not DEVICE_ID_RE.match(cleaned):
            raise ValueError("deviceId must look like PC-XXXXXXXX (uppercase hex)")
        return cleaned


class HeartbeatResponse(BaseModel):
    deviceId: str
    acknowledged: bool
    serverTime: datetime
    nextHeartbeatSeconds: int
    telemetryIntervalSeconds: int
    status: str


class TelemetrySummary(BaseModel):
    """The flattened "at a glance" values rendered on device cards."""

    timestamp: Optional[datetime] = None
    cpuUsage: Optional[float] = None
    gpuUsage: Optional[float] = None
    ramUsage: Optional[float] = None
    cpuTemperature: Optional[float] = None
    gpuTemperature: Optional[float] = None
    diskUsage: Optional[float] = None
    downloadMbps: Optional[float] = None
    uploadMbps: Optional[float] = None
    batteryPercent: Optional[float] = None


class DeviceSummary(BaseModel):
    deviceId: str
    name: str
    online: bool
    status: str = Field(..., description="online | offline")
    lastSeen: Optional[datetime] = None
    secondsSinceLastSeen: Optional[float] = None
    createdAt: Optional[datetime] = None
    agentVersion: Optional[str] = None
    os: Optional[str] = None
    architecture: Optional[str] = None
    hostname: Optional[str] = None
    cpuModel: Optional[str] = None
    gpuModel: Optional[str] = None
    ramTotalMB: Optional[float] = None
    diskTotalGB: Optional[float] = None
    telemetryIntervalSeconds: Optional[int] = None
    startupEnabled: Optional[bool] = None
    telemetryCount: Optional[int] = None
    metrics: Optional[TelemetrySummary] = None


class DeviceListResponse(BaseModel):
    devices: list[DeviceSummary]
    count: int
    onlineCount: int
    generatedAt: datetime
    refreshAfterSeconds: int


class DeviceDetailResponse(DeviceSummary):
    """Adds the full "current snapshot" for the device page header."""

    telemetryStored: int = 0
    retentionDays: int = 7
    retentionHours: int = 168
    supportedRanges: list[str] = Field(default_factory=list)
    recentLogs: list["LogEntry"] = Field(default_factory=list)


class DeviceSettingsUpdate(StrictModel):
    """Dashboard-driven preferences stored on the device document."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=MAX_DEVICE_NAME_LENGTH)
    telemetryIntervalSeconds: Optional[int] = Field(default=None, ge=10, le=3600)
    startupEnabled: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: Optional[str]) -> Optional[str]:
        return CONTROL_CHARS.sub("", value).strip() if value else value


class DeleteDeviceResponse(BaseModel):
    deviceId: str
    deleted: bool
    tokenRevoked: bool
    deletedTelemetry: Optional[int] = None
    message: str


class LogEntry(BaseModel):
    logId: Optional[str] = None
    deviceId: Optional[str] = None
    deviceName: Optional[str] = None
    event: str
    level: str = "info"
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[datetime] = None


class LogListResponse(BaseModel):
    logs: list[LogEntry]
    count: int
    generatedAt: datetime


DeviceDetailResponse.model_rebuild()
"""Telemetry models.

Every field is bounded so a buggy or tampered agent cannot poison the database
or blow up the dashboard (CPU/GPU/RAM above 100, negative speeds, absurd VRAM
figures, NaN values, and so on are all rejected with HTTP 422/400).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.device import DEVICE_ID_RE, StrictModel

MAX_PERCENT = 100.0
MAX_TEMPERATURE_C = 150.0
MIN_TEMPERATURE_C = -40.0
MAX_SPEED_MBPS = 100_000.0
MAX_MB = 4_194_304.0  # 4 TiB expressed in MB
MAX_CORES = 512


class TelemetryPayload(StrictModel):
    """A single sample produced by the Windows agent."""

    timestamp: datetime = Field(..., description="UTC sample time (ISO-8601)")
    deviceId: str = Field(..., description="Device that produced the sample")

    # CPU -----------------------------------------------------------------
    cpuUsage: Optional[float] = Field(default=None, ge=0, le=MAX_PERCENT)
    cpuPerCore: Optional[list[Optional[float]]] = Field(default=None, max_length=MAX_CORES)
    cpuFrequencyMHz: Optional[float] = Field(default=None, ge=0, le=100_000)
    cpuTemperature: Optional[float] = Field(
        default=None, ge=MIN_TEMPERATURE_C, le=MAX_TEMPERATURE_C
    )

    # GPU -----------------------------------------------------------------
    gpuUsage: Optional[float] = Field(default=None, ge=0, le=MAX_PERCENT)
    gpuTemperature: Optional[float] = Field(
        default=None, ge=MIN_TEMPERATURE_C, le=MAX_TEMPERATURE_C
    )
    vramUsedMB: Optional[float] = Field(default=None, ge=0, le=MAX_MB)
    vramTotalMB: Optional[float] = Field(default=None, ge=0, le=MAX_MB)

    # Memory --------------------------------------------------------------
    ramUsage: Optional[float] = Field(default=None, ge=0, le=MAX_PERCENT)
    ramUsedMB: Optional[float] = Field(default=None, ge=0, le=MAX_MB)
    ramTotalMB: Optional[float] = Field(default=None, ge=0, le=MAX_MB)
    ramAvailableMB: Optional[float] = Field(default=None, ge=0, le=MAX_MB)

    # Disk ----------------------------------------------------------------
    diskUsage: Optional[float] = Field(default=None, ge=0, le=MAX_PERCENT)
    diskTotalGB: Optional[float] = Field(default=None, ge=0, le=1_048_576)
    diskUsedGB: Optional[float] = Field(default=None, ge=0, le=1_048_576)
    diskFreeGB: Optional[float] = Field(default=None, ge=0, le=1_048_576)
    diskReadMbps: Optional[float] = Field(default=None, ge=0, le=MAX_SPEED_MBPS)
    diskWriteMbps: Optional[float] = Field(default=None, ge=0, le=MAX_SPEED_MBPS)

    # Network -------------------------------------------------------------
    downloadMbps: Optional[float] = Field(default=None, ge=0, le=MAX_SPEED_MBPS)
    uploadMbps: Optional[float] = Field(default=None, ge=0, le=MAX_SPEED_MBPS)
    apiLatencyMs: Optional[float] = Field(default=None, ge=0, le=600_000)

    # Battery (null on desktops) -----------------------------------------
    batteryPercent: Optional[float] = Field(default=None, ge=0, le=MAX_PERCENT)
    batteryCharging: Optional[bool] = None
    batteryTimeLeftSeconds: Optional[float] = Field(default=None, ge=0, le=31_536_000)

    # Misc ---------------------------------------------------------------
    uptimeSeconds: Optional[float] = Field(default=None, ge=0, le=315_360_000)

    @field_validator("deviceId")
    @classmethod
    def _validate_device_id(cls, value: str) -> str:
        cleaned = (value or "").strip().upper()
        if not DEVICE_ID_RE.match(cleaned):
            raise ValueError("deviceId must look like PC-XXXXXXXX (uppercase hex)")
        return cleaned

    @field_validator("cpuPerCore")
    @classmethod
    def _validate_per_core(
        cls, value: Optional[list[Optional[float]]]
    ) -> Optional[list[Optional[float]]]:
        if value is None:
            return None
        for item in value:
            if item is not None and not 0 <= float(item) <= MAX_PERCENT:
                raise ValueError("cpuPerCore values must be between 0 and 100")
        return value

    @field_validator("vramUsedMB", "ramUsedMB", "ramTotalMB", "ramAvailableMB", "diskUsedGB", "diskFreeGB")
    @classmethod
    def _round_storage_values(cls, value: Optional[float]) -> Optional[float]:
        return value

    def model_post_init(self, _context) -> None:  # noqa: D401 - pydantic hook
        """Cross-field sanity checks (VRAM used can never exceed VRAM total)."""
        if self.vramUsedMB is not None and self.vramTotalMB is not None:
            if self.vramUsedMB > self.vramTotalMB * 1.05:
                raise ValueError("vramUsedMB cannot exceed vramTotalMB")
        if self.ramUsedMB is not None and self.ramTotalMB is not None:
            if self.ramUsedMB > self.ramTotalMB * 1.05:
                raise ValueError("ramUsedMB cannot exceed ramTotalMB")


class TelemetryResponse(BaseModel):
    deviceId: str
    telemetryId: str
    receivedAt: datetime
    expiresAt: datetime
    retentionDays: int


class TelemetryPoint(BaseModel):
    """One point of a chart series (UTC timestamps, converted client side)."""

    timestamp: datetime
    cpuUsage: Optional[float] = None
    gpuUsage: Optional[float] = None
    ramUsage: Optional[float] = None
    cpuTemperature: Optional[float] = None
    gpuTemperature: Optional[float] = None
    diskUsage: Optional[float] = None
    downloadMbps: Optional[float] = None
    uploadMbps: Optional[float] = None
    diskReadMbps: Optional[float] = None
    diskWriteMbps: Optional[float] = None


class TelemetrySeriesResponse(BaseModel):
    deviceId: str
    range: str
    rangeHours: int
    startTime: datetime
    endTime: datetime
    resolutionSeconds: int
    count: int
    empty: bool
    truncated: bool
    maxPoints: int
    retentionDays: int
    points: list[TelemetryPoint] = Field(default_factory=list)


class TelemetryIngestSummary(BaseModel):
    accepted: int
    rejected: int
    oldestAcceptedSecondsAgo: Optional[float] = None
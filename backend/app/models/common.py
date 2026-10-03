"""Shared response envelopes, auth models and cleanup status models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field



class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    time: datetime
    uptimeSeconds: float
    retentionDays: int
    onlineThresholdSeconds: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None
    requestId: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class SuccessResponse(BaseModel):
    ok: bool = True
    message: str = ""


class ApiMetaResponse(BaseModel):
    name: str
    version: str
    environment: str
    retentionDays: int
    supportedRanges: list[str] = Field(default_factory=list)
    telemetryIntervalSeconds: int
    heartbeatIntervalSeconds: int
    onlineThresholdSeconds: int
    maxTelemetryPoints: int


class CleanupStatusResponse(BaseModel):
    enabled: bool
    retentionDays: int
    ttlPolicy: dict[str, Any] = Field(default_factory=dict)
    lastRunAt: Optional[datetime] = None
    lastRunResult: Optional[dict[str, Any]] = None
    totalErrors: int = 0
    expiredTelemetryPending: Optional[int] = None
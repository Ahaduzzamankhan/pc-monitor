"""Input validation helpers shared by routers and services."""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from fastapi import HTTPException, status

from app.core.config import SUPPORTED_RANGE_HOURS
from app.utils.time import from_iso, utcnow

#: Device ids are minted by the agent: ``PC-`` + 6..24 uppercase hex chars.
DEVICE_ID_PATTERN = re.compile(r"^PC-[A-F0-9]{6,24}$")
#: Loose semver-ish version string.
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$")
#: Names are free text but must stay single-line and short.
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_DEVICE_NAME_LENGTH = 64
MAX_MODEL_LENGTH = 160
MAX_OS_LENGTH = 120


class APIError(HTTPException):
    """HTTPException carrying a machine readable error code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message


def bad_request(code: str, message: str) -> APIError:
    return APIError(status.HTTP_400_BAD_REQUEST, code, message)


def unauthorized(code: str, message: str) -> APIError:
    return APIError(
        status.HTTP_401_UNAUTHORIZED,
        code,
        message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(code: str, message: str) -> APIError:
    return APIError(status.HTTP_403_FORBIDDEN, code, message)


def not_found(code: str, message: str) -> APIError:
    return APIError(status.HTTP_404_NOT_FOUND, code, message)


def payload_too_large(message: str) -> APIError:
    return APIError(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "payload_too_large", message)


def conflict(code: str, message: str) -> APIError:
    return APIError(status.HTTP_409_CONFLICT, code, message)


def rate_limited(message: str, retry_after: int) -> APIError:
    return APIError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate_limited",
        message,
        headers={"Retry-After": str(max(1, int(retry_after)))},
    )


def validate_device_id(device_id: Any) -> str:
    """Normalise and validate a device id, raising 400 on failure."""
    if not isinstance(device_id, str):
        raise bad_request("invalid_device_id", "deviceId must be a string")
    value = device_id.strip().upper()
    if not DEVICE_ID_PATTERN.match(value):
        raise bad_request(
            "invalid_device_id",
            "deviceId must look like PC-XXXXXXXX (uppercase hex)",
        )
    return value


def validate_version(value: Any, field: str = "agentVersion") -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not VERSION_PATTERN.match(value.strip()):
        raise bad_request("invalid_version", f"{field} is not a valid version string")
    return value.strip()


def clean_text(
    value: Any,
    *,
    field: str,
    max_length: int,
    required: bool = False,
) -> Optional[str]:
    """Strip control characters and enforce a maximum length."""
    if value is None:
        if required:
            raise bad_request("invalid_field", f"{field} is required")
        return None
    if not isinstance(value, str):
        raise bad_request("invalid_field", f"{field} must be a string")
    cleaned = CONTROL_CHARS.sub("", value).strip()
    if not cleaned:
        if required:
            raise bad_request("invalid_field", f"{field} must not be empty")
        return None
    if len(cleaned) > max_length:
        raise bad_request(
            "invalid_field", f"{field} must be at most {max_length} characters"
        )
    return cleaned


def parse_timestamp(value: Any, *, field: str = "timestamp") -> Optional[Any]:
    """Parse a required/optional ISO timestamp into aware UTC."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Epoch seconds are tolerated from the agent.
        from datetime import datetime, timezone

        if value > 1e11:  # milliseconds
            value = value / 1000.0
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        return from_iso(value)
    except ValueError as exc:
        raise bad_request("invalid_timestamp", str(exc)) from exc


def validate_range(
    value: Optional[str],
    *,
    max_hours: int,
    default: str = "6h",
) -> tuple[str, int]:
    """Validate a history range keyword and return ``(label, hours)``."""
    label = (value or default).strip().lower()
    if label not in SUPPORTED_RANGE_HOURS:
        raise bad_request(
            "invalid_range",
            "range must be one of " + ", ".join(SUPPORTED_RANGE_HOURS),
        )
    hours = SUPPORTED_RANGE_HOURS[label]
    if hours > max_hours:
        raise bad_request(
            "range_too_large",
            f"range {label} exceeds the {max_hours}h retention window",
        )
    return label, hours


def clamp_percent(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return max(0.0, min(100.0, round(float(value), 2)))


def non_negative(value: Optional[float], digits: int = 3) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    if value < 0:
        return 0.0
    return round(value, digits)


def is_within_retention(timestamp: Any, retention_seconds: int, max_skew_seconds: int) -> bool:
    """Reject samples that are too old to retain or too far in the future."""
    now = utcnow()
    age = (now - timestamp).total_seconds()
    if age > retention_seconds:
        raise bad_request(
            "telemetry_too_old",
            "sample is older than the configured retention window",
        )
    if age < -max_skew_seconds:
        raise bad_request(
            "invalid_timestamp",
            "sample timestamp is too far in the future",
        )
    return True


def ensure_finite_numbers(payload: dict[str, Any], keys: Iterable[str]) -> None:
    """Reject NaN/Infinity which Firestore cannot store."""
    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            continue
        if value != value or value in (float("inf"), float("-inf")):
            raise bad_request("invalid_number", f"{key} must be a finite number")
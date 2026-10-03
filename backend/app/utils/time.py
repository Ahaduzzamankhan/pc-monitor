"""UTC time helpers.

Every timestamp produced or accepted by the backend is timezone-aware UTC and
serialised as an ISO-8601 string with a trailing ``Z`` so the Next.js frontend
can render local time unambiguously.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Attach UTC to a naive datetime, convert an aware one to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_iso(value: Optional[datetime]) -> Optional[str]:
    """ISO-8601 string with a ``Z`` suffix, or ``None``."""
    if value is None:
        return None
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def from_iso(value: Optional[str | datetime]) -> Optional[datetime]:
    """Parse an ISO-8601 string (``Z`` or offset) into aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return ensure_utc(datetime.fromisoformat(text))
    except ValueError as exc:  # pragma: no cover - exercised via validation
        raise ValueError(f"invalid ISO-8601 timestamp: {value!r}") from exc


def hours_ago(hours: float) -> datetime:
    return utcnow() - timedelta(hours=hours)


def seconds_ago(seconds: float) -> datetime:
    return utcnow() - timedelta(seconds=seconds)
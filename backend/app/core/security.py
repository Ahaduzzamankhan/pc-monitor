"""Security primitives.

Two independent trust domains exist in PC Monitor:

* **Agents** authenticate with a per-device token issued at registration.  Only
  an HMAC-SHA256 hash of that token is persisted, so a database leak cannot be
  replayed against the API.
* **Agents** are the only authenticated callers of the write endpoints.

Neither secret is ever returned to the browser or embedded in the agent.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any, Optional

from app.core.config import Settings

TOKEN_BYTES = 32
SESSION_KEY_BYTES = 32


# ---------------------------------------------------------------------------
# Device identity
# ---------------------------------------------------------------------------
def generate_device_id() -> str:
    """Mint a device id such as ``PC-7F42A91C`` (cryptographically random)."""
    return f"PC-{secrets.token_hex(4).upper()}"


def generate_device_token() -> str:
    """Mint a 256-bit URL-safe device token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_device_token(token: str, settings: Settings) -> str:
    """Peppered HMAC hash of a device token (never store the raw token)."""
    if not token:
        return ""
    return hmac.new(
        settings.device_auth_secret.get_secret_value().encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def token_fingerprint(token: str) -> str:
    """Short, non-reversible fingerprint safe to show in logs/UI."""
    if not token:
        return "none"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def verify_device_token(token: str, stored_hash: str, settings: Settings) -> bool:
    """Constant-time verification of a presented token."""
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(hash_device_token(token, settings), stored_hash)


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest((left or "").encode("utf-8"), (right or "").encode("utf-8"))


def generate_secret() -> str:
    """Generate a strong DEVICE_AUTH_SECRET for operators."""
    return secrets.token_urlsafe(SESSION_KEY_BYTES)
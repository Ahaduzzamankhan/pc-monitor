"""Application configuration loaded from environment variables / .env file.

Every setting is read from the environment so secrets stay outside the
repository.  Nothing in this module is ever exposed to the browser or bundled
into the Windows agent.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Hard ceiling for telemetry retention.  The product requirement is that
#: history may never exceed 7 days, regardless of configuration.
MAX_RETENTION_DAYS = 7

#: Hard ceiling for the dashboard history ranges (1h / 6h / 24h / 7d).
SUPPORTED_RANGE_HOURS: dict[str, int] = {"1h": 1, "6h": 6, "24h": 24, "7d": 24 * 7}


class Settings(BaseSettings):
    """Runtime settings for the PC Monitor backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application -------------------------------------------------------
    app_name: str = "PC Monitor API"
    version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # -- CORS / frontend ---------------------------------------------------
    frontend_url: str = "http://localhost:3000"
    #: Comma separated list of extra browser origins.  Declared as a plain
    #: string because pydantic-settings JSON-decodes complex env values before
    #: field validators run, which rejects "a,b" syntax.
    extra_cors_origins: str = ""

    # -- Firebase (server side only) --------------------------------------
    firebase_project_id: Optional[str] = None
    firebase_client_email: Optional[str] = None
    firebase_private_key: Optional[SecretStr] = None
    google_application_credentials: Optional[str] = None
    firestore_database: str = "(default)"
    #: Use the in-process store instead of Firestore (local dev / tests).
    use_inmemory_db: bool = False

    #: Derived at validation time - declared so pydantic allows assignment.
    firestore_enabled: bool = False

    # -- Device authentication --------------------------------------------
    #: Pepper used to derive device-token hashes (HMAC-SHA256).
    device_auth_secret: SecretStr = Field(
        default=SecretStr("insecure-development-secret-change-me")
    )

    # -- Retention / online thresholds ------------------------------------
    telemetry_retention_days: int = Field(default=7, ge=1, le=MAX_RETENTION_DAYS)
    online_threshold_seconds: int = Field(default=120, ge=15, le=3600)
    default_telemetry_interval_seconds: int = Field(default=30, ge=10, le=3600)
    max_telemetry_points: int = Field(default=1500, ge=50, le=20000)
    #: Reject agent samples that are further than this in the future.
    max_future_clock_skew_seconds: int = Field(default=300, ge=0, le=86_400)

    # -- Request protection ------------------------------------------------
    max_request_bytes: int = Field(default=64 * 1024, ge=1024, le=4 * 1024 * 1024)
    rate_limit_telemetry_per_minute: int = Field(default=12, ge=1, le=600)
    rate_limit_heartbeat_per_minute: int = Field(default=20, ge=1, le=600)
    rate_limit_register_per_hour: int = Field(default=30, ge=1, le=6000)
    rate_limit_dashboard_per_minute: int = Field(default=300, ge=10, le=6000)

    # -- Cleanup / TTL -----------------------------------------------------
    cleanup_interval_minutes: int = Field(default=30, ge=1, le=1440)
    cleanup_batch_size: int = Field(default=400, ge=1, le=500)
    cleanup_page_size: int = Field(default=200, ge=1, le=500)
    cleanup_max_pages_per_run: int = Field(default=50, ge=1, le=1000)
    enable_ttl_policy: bool = True
    #: Shared secret for POST /internal/cleanup (cron / scheduler friendly).
    cleanup_secret: Optional[SecretStr] = None

    @field_validator("frontend_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("extra_cors_origins", mode="before")
    @classmethod
    def _normalise_origins(cls, value: object) -> str:
        if isinstance(value, (list, tuple)):
            return ",".join(str(item) for item in value)
        return str(value or "")

    @field_validator("device_auth_secret")
    @classmethod
    def _require_strong_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value() or ""
        if len(secret) < 16:
            raise ValueError("DEVICE_AUTH_SECRET must be at least 16 characters long")
        return value

    @model_validator(mode="after")
    def _derive_runtime_flags(self) -> "Settings":
        # Firestore is only usable when a project id has been configured, unless
        # the in-memory store was requested explicitly.
        self.firestore_enabled = bool(
            not self.use_inmemory_db and self.firebase_project_id
        )
        return self

    # -- Derived helpers ---------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def retention_seconds(self) -> int:
        return self.telemetry_retention_days * 24 * 3600

    @property
    def cors_origin_list(self) -> List[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.extra_cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def allowed_origins(self) -> List[str]:
        origins = {self.frontend_url, *self.cors_origin_list}
        return sorted(origin for origin in origins if origin)

    def max_range_hours(self) -> int:
        """The longest history window the backend is allowed to serve."""
        return min(SUPPORTED_RANGE_HOURS["7d"], self.retention_seconds // 3600)

    def supported_ranges(self) -> List[str]:
        """History ranges that both the UI and the retention policy allow."""
        return [name for name, hours in SUPPORTED_RANGE_HOURS.items() if hours <= self.max_range_hours()]

    def private_key(self) -> Optional[str]:
        if self.firebase_private_key is None:
            return None
        return self.firebase_private_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (usable as a FastAPI dependency)."""
    return Settings()


def reload_settings() -> Settings:
    """Clear the cache - used by tests that mutate the environment."""
    get_settings.cache_clear()
    return get_settings()
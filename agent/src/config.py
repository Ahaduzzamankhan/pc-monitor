"""Agent configuration and local (token-protected) storage.

Files live under ``%LOCALAPPDATA%\\PC-Monitor``:

``config.json``  device id, device name, API url, intervals, startup flag
``token.dat``    the device token, encrypted with Windows DPAPI when available

Environment variables (useful for testing or a managed deployment):

``API_URL``                    backend base url, e.g. https://api.example.com
``TELEMETRY_INTERVAL_SECONDS`` sampling interval (default 30)
``PC_MONITOR_HOME``            override the configuration directory
``PC_MONITOR_DEVICE_NAME``     friendly name shown in the dashboard
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.logger import app_data_dir, get_logger

logger = get_logger()

CONFIG_FILENAME = "config.json"
TOKEN_FILENAME = "token.dat"
DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_INTERVAL_SECONDS = 30
MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 3600


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid_env", "ignoring non-numeric environment value", name=name)
        return default


@dataclass
class AgentConfig:
    """Runtime configuration for the agent."""

    device_id: str = ""
    device_name: str = ""
    api_url: str = DEFAULT_API_URL
    telemetry_interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    heartbeat_interval_seconds: int = 60
    startup_enabled: bool = True
    server_telemetry_interval: Optional[int] = None
    registered: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    # -- paths -------------------------------------------------------------
    @property
    def directory(self) -> Path:
        return app_data_dir()

    @property
    def config_path(self) -> Path:
        return self.directory / CONFIG_FILENAME

    @property
    def token_path(self) -> Path:
        return self.directory / TOKEN_FILENAME

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def load(cls) -> "AgentConfig":
        """Load config from disk, then apply environment overrides."""
        config = cls()
        path = config.config_path
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.error("config_unreadable", "starting with defaults", error=str(exc))
                data = {}
            known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
            for key, value in data.items():
                if key in known:
                    setattr(config, key, value)
                else:
                    config.extra[key] = value

        env_url = os.environ.get("API_URL")
        if env_url:
            config.api_url = env_url.rstrip("/")
        env_name = os.environ.get("PC_MONITOR_DEVICE_NAME")
        if env_name:
            config.device_name = env_name
        config.telemetry_interval_seconds = _clamp_interval(
            _env_int("TELEMETRY_INTERVAL_SECONDS", int(config.telemetry_interval_seconds))
        )
        config.startup_enabled = str(
            os.environ.get("PC_MONITOR_STARTUP", str(config.startup_enabled))
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not config.device_name:
            config.device_name = default_device_name()
        return config

    def save(self) -> None:
        """Persist the configuration atomically."""
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload.pop("extra", None)
        payload.update(self.extra)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.config_path)
        # The config file itself never contains the token.
        logger.info(
            "config_saved",
            "configuration stored",
            path=str(self.config_path),
            deviceId=self.device_id,
            telemetryIntervalSeconds=self.telemetry_interval_seconds,
        )

    # -- token -------------------------------------------------------------
    def load_token(self) -> str:
        """Decrypt and return the stored device token (empty when absent)."""
        if not self.token_path.exists():
            return ""
        try:
            blob = self.token_path.read_bytes()
        except OSError as exc:
            logger.error("token_unreadable", "could not read token file", error=str(exc))
            return ""
        return decrypt_token(blob)

    def save_token(self, token: str) -> None:
        """Encrypt and store the device token."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.token_path.write_bytes(encrypt_token(token))
        logger.info("token_stored", "device token stored securely", path=str(self.token_path))

    def clear_token(self) -> None:
        try:
            self.token_path.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - permission issues
            logger.warning("token_clear_failed", "could not delete token file", error=str(exc))


# ---------------------------------------------------------------------------
# Token encryption (Windows DPAPI, with an explicit non-Windows fallback)
# ---------------------------------------------------------------------------
IS_WINDOWS = sys.platform == "win32"


def _dpapi_protect(data: bytes) -> Optional[bytes]:
    """Encrypt with DPAPI (CryptProtectData) - no third-party dependency."""
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        buffer = ctypes.create_string_buffer(data, len(data))
        in_blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(in_blob), None, None, None, None, 0x01, ctypes.byref(out_blob)
        ):
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:  # pragma: no cover - depends on Windows API availability
        return None


def _dpapi_unprotect(blob: bytes) -> Optional[bytes]:
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        buffer = ctypes.create_string_buffer(blob, len(blob))
        in_blob = DATA_BLOB(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0x01, ctypes.byref(out_blob)
        ):
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:  # pragma: no cover
        return None


def _machine_key() -> bytes:
    """Fallback key material for non-Windows development runs."""
    import hashlib
    import uuid

    seed = f"{uuid.getnode()}:{os.environ.get('USERNAME', 'dev')}"
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))


def encrypt_token(token: str) -> bytes:
    """Encrypt the token; DPAPI on Windows, obfuscation elsewhere (dev only)."""
    raw = token.encode("utf-8")
    protected = _dpapi_protect(raw)
    if protected is not None:
        return b"DPAPI" + protected
    return b"LOCAL" + _xor(raw, _machine_key())


def decrypt_token(blob: bytes) -> str:
    """Reverse :func:`encrypt_token`."""
    try:
        if blob.startswith(b"DPAPI"):
            plain = _dpapi_unprotect(blob[5:])
            return plain.decode("utf-8") if plain else ""
        if blob.startswith(b"LOCAL"):
            return _xor(blob[5:], _machine_key()).decode("utf-8")
    except Exception as exc:  # pragma: no cover - corrupted token file
        logger.error("token_decrypt_failed", "could not decrypt token", error=str(exc))
    return ""


def _clamp_interval(value: int) -> int:
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, int(value)))


def default_device_name() -> str:
    """Friendly default name, e.g. ``DESKTOP-FOO`` -> ``Foo``."""
    hostname = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "PC"
    cleaned = hostname.replace(".local", "").split(".")[0]
    return cleaned[:64] or "PC"


def app_version() -> str:
    from src import __version__

    return __version__
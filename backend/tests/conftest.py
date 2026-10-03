"""Pytest configuration and shared fixtures for the backend test-suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Test environment: in-memory store, no Firebase, fixed secrets.
os.environ.setdefault("USE_INMEMORY_DB", "true")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEVICE_AUTH_SECRET", "test-device-auth-secret-value-0123456789")
os.environ.setdefault("CLEANUP_SECRET", "test-cleanup-secret")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.firebase import InMemoryStore, set_store  # noqa: E402
from app.core.middleware import limiter  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import cleanup_service, device_service, telemetry_service  # noqa: E402

DASHBOARD_PASSWORD = "test-password"  # kept for tests that assert it is unused


@pytest.fixture
def settings():
    """The live settings object the running app also uses."""
    return get_settings()


@pytest.fixture(autouse=True)
def _restore_settings():
    """Undo settings mutations so a test cannot leak configuration."""
    current = get_settings()
    snapshot = dict(current.__dict__)
    yield current
    current.__dict__.clear()
    current.__dict__.update(snapshot)


@pytest.fixture(autouse=True)
def clean_state():
    """Every test starts with a pristine store, service cache and rate limiter."""
    store = InMemoryStore()
    set_store(store)
    limiter.reset()
    device_service.reset_device_service()
    telemetry_service.reset_telemetry_service()
    cleanup_service.reset_cleanup_service()
    yield store
    set_store(None)
    device_service.reset_device_service()
    telemetry_service.reset_telemetry_service()
    cleanup_service.reset_cleanup_service()


@pytest.fixture
def store(clean_state):
    return clean_state


@pytest.fixture
def client():
    """Dashboard client - the dashboard is intentionally open by design."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client):
    """Alias kept for readability: dashboard routes no longer require a session."""
    return client


def register_device(
    client,
    device_id="PC-00000001",
    name="Home PC",
    token=None,
) -> dict:
    payload = {
        "deviceId": device_id,
        "name": name,
        "agentVersion": "1.0.0",
        "os": "Windows 11 Pro",
        "architecture": "AMD64",
        "cpuModel": "AMD Ryzen 7 5800X",
        "gpuModel": "NVIDIA GeForce RTX 3070",
        "ramTotalMB": 32768,
    }
    headers = {"X-Device-Token": token} if token else {}
    response = client.post("/api/devices/register", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def telemetry_payload(device_id: str, timestamp: str, **overrides) -> dict:
    payload = {
        "deviceId": device_id,
        "timestamp": timestamp,
        "cpuUsage": 42.5,
        "cpuTemperature": 55.0,
        "gpuUsage": 61.0,
        "gpuTemperature": 58.0,
        "ramUsage": 62.5,
        "diskUsage": 71.0,
        "downloadMbps": 8.4,
        "uploadMbps": 1.2,
    }
    payload.update(overrides)
    return payload
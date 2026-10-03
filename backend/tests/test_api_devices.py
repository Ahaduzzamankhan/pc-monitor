"""Core API behaviour: health, registration, discovery, device pages, removal."""

from __future__ import annotations

from datetime import timedelta

from app.utils.time import to_iso, utcnow
from tests.conftest import register_device, telemetry_payload


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["retentionDays"] == 7


def test_openapi_and_docs_available(client):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_device_registration_issues_token_once(client, store):
    data = register_device(client)
    assert data["deviceId"] == "PC-00000001"
    assert data["created"] is True
    assert len(data["token"]) >= 32
    assert data["retentionDays"] == 7

    stored = store.get_device("PC-00000001")
    assert stored["name"] == "Home PC"
    # The raw token is never persisted.
    assert data["token"] not in str(stored)
    assert len(stored["tokenHash"]) == 64


def test_device_list_is_served_without_login(client):
    register_device(client)
    response = client.get("/api/devices")
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_devices_are_discovered_automatically(auth_client):
    register_device(auth_client, "PC-00000001", "Home PC")
    register_device(auth_client, "PC-00000002", "Gaming PC")
    register_device(auth_client, "PC-00000003", "Laptop")

    body = auth_client.get("/api/devices").json()
    assert body["count"] == 3
    assert {device["name"] for device in body["devices"]} == {"Home PC", "Gaming PC", "Laptop"}


def test_offline_device_reports_last_seen(auth_client):
    from app.core.firebase import get_store

    register_device(auth_client)
    get_store().update_device(
        "PC-00000001", {"lastSeen": to_iso(utcnow() - timedelta(minutes=14))}
    )

    body = auth_client.get("/api/devices").json()
    device = body["devices"][0]
    assert device["online"] is False
    assert device["status"] == "offline"
    assert device["secondsSinceLastSeen"] > 13 * 60


def test_telemetry_makes_device_online_with_metrics(auth_client):
    registration = register_device(auth_client)
    token = registration["token"]
    response = auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": token},
    )
    assert response.status_code == 202

    device = auth_client.get("/api/devices").json()["devices"][0]
    assert device["online"] is True
    assert device["metrics"]["cpuUsage"] == 42.5
    assert device["metrics"]["gpuTemperature"] == 58.0


def test_device_detail_page_data(auth_client):
    registration = register_device(auth_client)
    auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": registration["token"]},
    )
    detail = auth_client.get("/api/devices/PC-00000001").json()
    assert detail["name"] == "Home PC"
    assert detail["agentVersion"] == "1.0.0"
    assert detail["os"] == "Windows 11 Pro"
    assert detail["cpuModel"] == "AMD Ryzen 7 5800X"
    assert detail["gpuModel"] == "NVIDIA GeForce RTX 3070"
    assert detail["telemetryStored"] == 1
    assert detail["supportedRanges"] == ["1h", "6h", "24h", "7d"]
    assert any(entry["event"] == "device_registered" for entry in detail["recentLogs"])


def test_unknown_device_returns_404(auth_client):
    response = auth_client.get("/api/devices/PC-DEADBEEF")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "device_not_found"


def test_device_settings_update(auth_client):
    register_device(auth_client)
    response = auth_client.patch(
        "/api/devices/PC-00000001",
        json={"name": "Renamed PC", "telemetryIntervalSeconds": 60, "startupEnabled": True},
    )
    assert response.status_code == 200
    detail = auth_client.get("/api/devices/PC-00000001").json()
    assert detail["name"] == "Renamed PC"
    assert detail["telemetryIntervalSeconds"] == 60
    assert detail["startupEnabled"] is True


def test_device_removal_revokes_token(auth_client):
    registration = register_device(auth_client)
    token = registration["token"]
    auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": token},
    )

    response = auth_client.delete("/api/devices/PC-00000001")
    assert response.status_code == 200
    body = response.json()
    assert body["tokenRevoked"] is True
    assert body["deletedTelemetry"] == 1

    # The device page is gone and the old token no longer works.
    assert auth_client.get("/api/devices/PC-00000001").status_code == 404
    rejected = auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": token},
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "device_revoked"


def test_removed_device_can_be_registered_again(auth_client):
    registration = register_device(auth_client)
    auth_client.delete("/api/devices/PC-00000001")

    fresh = auth_client.post(
        "/api/devices/register",
        json={
            "deviceId": "PC-00000001",
            "name": "Home PC",
            "agentVersion": "1.0.0",
            "os": "Windows 11 Pro",
        },
    )
    assert fresh.status_code == 201
    assert fresh.json()["token"] != registration["token"]

    accepted = auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": fresh.json()["token"]},
    )
    assert accepted.status_code == 202


def test_duplicate_registration_without_token_conflicts(client):
    register_device(client)
    conflict = client.post(
        "/api/devices/register",
        json={
            "deviceId": "PC-00000001",
            "name": "Impostor",
            "agentVersion": "1.0.0",
            "os": "Windows 11",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "device_already_registered"


def test_reregistration_with_token_rotates_it(client):
    first = register_device(client)
    response = client.post(
        "/api/devices/register",
        json={
            "deviceId": "PC-00000001",
            "name": "Home PC",
            "agentVersion": "1.0.1",
            "os": "Windows 11 Pro",
        },
        headers={"X-Device-Token": first["token"]},
    )
    assert response.status_code == 201
    assert response.json()["created"] is False
    assert response.json()["token"] != first["token"]

    # The previous token is dead after rotation.
    stale = client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": first["token"]},
    )
    assert stale.status_code == 401
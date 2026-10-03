"""Device token authentication (the only trust boundary that remains)."""

from __future__ import annotations

from app.core.security import (
    generate_device_id,
    generate_device_token,
    hash_device_token,
    verify_device_token,
)
from app.utils.time import to_iso, utcnow
from tests.conftest import register_device, telemetry_payload


def test_generated_ids_and_tokens_are_cryptographically_random():
    ids = {generate_device_id() for _ in range(200)}
    tokens = {generate_device_token() for _ in range(200)}
    assert len(ids) == 200
    assert len(tokens) == 200
    assert all(value.startswith("PC-") and len(value) == 11 for value in ids)
    assert min(len(token) for token in tokens) >= 40


def test_token_hash_is_peppered_and_verifiable(settings):
    token = generate_device_token()
    stored = hash_device_token(token, settings)
    assert stored != token
    assert len(stored) == 64
    assert verify_device_token(token, stored, settings) is True
    assert verify_device_token(token + "x", stored, settings) is False
    assert verify_device_token("", stored, settings) is False


def test_agent_endpoints_reject_missing_token(client):
    register_device(client)
    response = client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_agent_endpoints_reject_wrong_token(client):
    registration = register_device(client)
    response = client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": registration["token"][:-4] + "AAAA"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_heartbeat_rejects_wrong_token(client):
    registration = register_device(client)
    response = client.post(
        "/api/devices/heartbeat",
        json={
            "deviceId": "PC-00000001",
            "timestamp": to_iso(utcnow()),
            "agentVersion": "1.0.0",
        },
        headers={"X-Device-Token": registration["token"][:-2] + "zz"},
    )
    assert response.status_code == 401


def test_bearer_token_is_accepted(client):
    registration = register_device(client)
    response = client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"Authorization": f"Bearer {registration['token']}"},
    )
    assert response.status_code == 202


def test_heartbeat_requires_registration(client):
    response = client.post(
        "/api/devices/heartbeat",
        json={
            "deviceId": "PC-00000099",
            "timestamp": to_iso(utcnow()),
            "agentVersion": "1.0.0",
        },
        headers={"X-Device-Token": "irrelevant"},
    )
    assert response.status_code == 401


def test_heartbeat_refreshes_agent_version_and_status(client):
    registration = register_device(client)
    response = client.post(
        "/api/devices/heartbeat",
        json={
            "deviceId": "PC-00000001",
            "timestamp": to_iso(utcnow()),
            "agentVersion": "1.0.2",
        },
        headers={"X-Device-Token": registration["token"]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "online"
    device = client.get("/api/devices").json()["devices"][0]
    assert device["agentVersion"] == "1.0.2"


def test_tokens_are_never_exposed_by_the_api(client):
    registration = register_device(client)
    token = registration["token"]
    for path in ("/api/devices", "/api/devices/PC-00000001", "/api/logs"):
        response = client.get(path)
        assert token not in response.text
        assert "tokenHash" not in response.text
        assert "tokenFingerprint" not in response.text


def test_dashboard_routes_are_open_by_design(client):
    """No in-app login: the dashboard is protected at the edge (Vercel/network)."""
    register_device(client)
    assert client.get("/api/devices").status_code == 200
    assert client.get("/api/devices/PC-00000001").status_code == 200
    assert client.get("/api/devices/PC-00000001/logs").status_code == 200
    assert client.post("/api/auth/login", json={"password": "x"}).status_code == 404
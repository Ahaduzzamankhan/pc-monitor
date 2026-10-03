"""Rate limiting, payload size limits and error-envelope shape."""

from __future__ import annotations

import json

from app.utils.time import to_iso, utcnow
from tests.conftest import register_device, telemetry_payload


def test_telemetry_endpoint_is_rate_limited(client, settings):
    token = register_device(client)["token"]
    settings.rate_limit_telemetry_per_minute = 3

    statuses = []
    for _ in range(5):
        response = client.post(
            "/api/telemetry",
            json=telemetry_payload("PC-00000001", to_iso(utcnow())),
            headers={"X-Device-Token": token},
        )
        statuses.append(response.status_code)

    assert statuses[:3] == [202, 202, 202]
    assert statuses[3] == 429
    limited = client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": token},
    )
    assert limited.headers.get("retry-after")
    assert limited.json()["error"]["code"] == "rate_limited"


def test_heartbeat_endpoint_is_rate_limited(client, settings):
    token = register_device(client)["token"]
    settings.rate_limit_heartbeat_per_minute = 2
    body = {
        "deviceId": "PC-00000001",
        "timestamp": to_iso(utcnow()),
        "agentVersion": "1.0.0",
    }
    headers = {"X-Device-Token": token}
    codes = [
        client.post("/api/devices/heartbeat", json=body, headers=headers).status_code
        for _ in range(4)
    ]
    assert codes[:2] == [200, 200]
    assert 429 in codes[2:]


def test_registration_endpoint_is_rate_limited(client, settings):
    settings.rate_limit_register_per_hour = 1
    payload = {
        "deviceId": "PC-00000007",
        "name": "PC",
        "agentVersion": "1.0.0",
        "os": "Windows 11",
    }
    assert client.post("/api/devices/register", json=payload).status_code == 201
    assert client.post("/api/devices/register", json=payload).status_code == 429


def test_dashboard_routes_are_rate_limited(auth_client, settings):
    settings.rate_limit_dashboard_per_minute = 5
    codes = [auth_client.get("/api/devices").status_code for _ in range(8)]
    assert codes[:5] == [200] * 5
    assert 429 in codes[5:]


def test_oversized_request_body_is_rejected(client, settings):
    token = register_device(client)["token"]
    payload = telemetry_payload("PC-00000001", to_iso(utcnow()))
    payload["cpuPerCore"] = [50.0] * 40000
    raw = json.dumps(payload).encode("utf-8")
    assert len(raw) > settings.max_request_bytes
    response = client.post(
        "/api/telemetry",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Device-Token": token,
        },
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_error_envelope_shape(client):
    register_device(client)
    response = client.get("/api/devices/PC-DEADBEEF/telemetry")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) >= {"code", "message"}


def test_unknown_route_returns_structured_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_security_headers_are_present(client):
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
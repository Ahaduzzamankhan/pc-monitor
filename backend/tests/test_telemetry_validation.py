"""Telemetry validation: bounds, ranges and history windows."""

from __future__ import annotations

from datetime import timedelta

from app.utils.time import to_iso, utcnow
from tests.conftest import register_device, telemetry_payload


def _post(client, device_id, token, **overrides):
    payload = telemetry_payload(device_id, to_iso(utcnow()), **overrides)
    return client.post("/api/telemetry", json=payload, headers={"X-Device-Token": token})


def test_valid_sample_is_accepted(client):
    token = register_device(client)["token"]
    response = _post(client, "PC-00000001", token, cpuPerCore=[10.0, 55.5, None])
    assert response.status_code == 202
    body = response.json()
    assert body["retentionDays"] == 7
    assert body["expiresAt"]


def test_percentage_above_100_is_rejected(client):
    token = register_device(client)["token"]
    for field in ("cpuUsage", "gpuUsage", "ramUsage", "diskUsage"):
        response = _post(client, "PC-00000001", token, **{field: 120.0})
        assert response.status_code == 422, field
        assert response.json()["error"]["code"] == "validation_error"


def test_negative_values_are_rejected(client):
    token = register_device(client)["token"]
    for field in ("downloadMbps", "uploadMbps", "ramUsedMB", "diskReadMbps", "uptimeSeconds"):
        response = _post(client, "PC-00000001", token, **{field: -1})
        assert response.status_code == 422, field


def test_out_of_range_temperatures_are_rejected(client):
    token = register_device(client)["token"]
    assert _post(client, "PC-00000001", token, cpuTemperature=250).status_code == 422
    assert _post(client, "PC-00000001", token, gpuTemperature=-80).status_code == 422


def test_vram_used_cannot_exceed_total(client):
    token = register_device(client)["token"]
    response = _post(
        client, "PC-00000001", token, vramUsedMB=9000, vramTotalMB=8000
    )
    assert response.status_code == 422


def test_unknown_fields_are_rejected(client):
    token = register_device(client)["token"]
    payload = telemetry_payload("PC-00000001", to_iso(utcnow()))
    payload["screenshot"] = "should never be accepted"
    response = client.post(
        "/api/telemetry", json=payload, headers={"X-Device-Token": token}
    )
    assert response.status_code == 422


def test_invalid_device_id_is_rejected(client):
    token = register_device(client)["token"]
    payload = telemetry_payload("not-a-device", to_iso(utcnow()))
    response = client.post("/api/telemetry", json=payload, headers={"X-Device-Token": token})
    assert response.status_code in (400, 422)


def test_missing_timestamp_is_rejected(client):
    token = register_device(client)["token"]
    payload = telemetry_payload("PC-00000001", to_iso(utcnow()))
    payload.pop("timestamp")
    response = client.post("/api/telemetry", json=payload, headers={"X-Device-Token": token})
    assert response.status_code == 422


def test_malformed_timestamp_is_rejected(client):
    token = register_device(client)["token"]
    payload = telemetry_payload("PC-00000001", "not-a-timestamp")
    response = client.post("/api/telemetry", json=payload, headers={"X-Device-Token": token})
    assert response.status_code == 422


def test_samples_older_than_retention_are_rejected(client):
    token = register_device(client)["token"]
    old = to_iso(utcnow() - timedelta(days=8))
    response = client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", old),
        headers={"X-Device-Token": token},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "telemetry_too_old"


def test_samples_far_in_the_future_are_rejected(client):
    token = register_device(client)["token"]
    future = to_iso(utcnow() + timedelta(hours=2))
    response = client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", future),
        headers={"X-Device-Token": token},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_timestamp"


def test_oversized_payload_is_rejected(client):
    token = register_device(client)["token"]
    payload = telemetry_payload("PC-00000001", to_iso(utcnow()))
    payload["cpuPerCore"] = [50.0] * 5000
    response = client.post(
        "/api/telemetry", json=payload, headers={"X-Device-Token": token}
    )
    assert response.status_code in (413, 422)


def test_history_ranges(auth_client):
    token = register_device(auth_client)["token"]
    auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": token},
    )
    for label, hours in (("1h", 1), ("6h", 6), ("24h", 24), ("7d", 168)):
        response = auth_client.get(f"/api/devices/PC-00000001/telemetry?range={label}")
        assert response.status_code == 200, label
        body = response.json()
        assert body["range"] == label
        assert body["rangeHours"] == hours
        assert body["count"] == 1
        assert body["empty"] is False
        assert body["points"][0]["cpuUsage"] == 42.5


def test_invalid_range_is_rejected(auth_client):
    register_device(auth_client)
    response = auth_client.get("/api/devices/PC-00000001/telemetry?range=30d")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_range"


def test_history_cannot_exceed_seven_days(auth_client):
    register_device(auth_client)
    from app.core.config import MAX_RETENTION_DAYS

    assert MAX_RETENTION_DAYS == 7
    response = auth_client.get("/api/devices/PC-00000001/telemetry?range=7d")
    assert response.status_code == 200
    # Anything longer than 7 days is not a supported keyword at all.
    assert auth_client.get("/api/devices/PC-00000001/telemetry?range=8d").status_code == 400


def test_empty_history_is_handled(auth_client):
    register_device(auth_client)
    body = auth_client.get("/api/devices/PC-00000001/telemetry?range=1h").json()
    assert body["empty"] is True
    assert body["count"] == 0
    assert body["points"] == []


def test_history_is_downsampled_to_max_points(auth_client, store):
    token = register_device(auth_client)["token"]
    now = utcnow()
    for index in range(2200):
        store.append_telemetry(
            "PC-00000001",
            {
                "deviceId": "PC-00000001",
                "timestamp": now - timedelta(seconds=30 * index),
                "expiresAt": now - timedelta(seconds=30 * index) + timedelta(days=7),
                "cpuUsage": float(index % 100),
            },
        )
    body = auth_client.get("/api/devices/PC-00000001/telemetry?range=24h").json()
    assert body["count"] <= 1500
    assert body["truncated"] is True
    timestamps = [point["timestamp"] for point in body["points"]]
    assert timestamps == sorted(timestamps)


def test_telemetry_for_unknown_device_is_rejected(client):
    register_device(client)
    response = client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000042", to_iso(utcnow())),
        headers={"X-Device-Token": "whatever"},
    )
    assert response.status_code == 401
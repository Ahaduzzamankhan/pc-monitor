"""Retention: Firestore TTL metadata, the cleanup fallback and independence."""

from __future__ import annotations

from datetime import timedelta

from app.core.firebase import get_store
from app.services.cleanup_service import CleanupService
from app.utils.time import from_iso, to_iso, utcnow
from tests.conftest import register_device, telemetry_payload


def _sample(device_id: str, age: timedelta, **overrides) -> dict:
    timestamp = utcnow() - age
    payload = {
        "deviceId": device_id,
        "timestamp": to_iso(timestamp),
        "cpuUsage": 30.0,
    }
    payload.update(overrides)
    return {
        **payload,
        "expiresAt": to_iso(timestamp + timedelta(days=7)),
        "receivedAt": to_iso(timestamp),
    }


def test_telemetry_documents_carry_expires_at(auth_client, store):
    token = register_device(auth_client)["token"]
    auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow())),
        headers={"X-Device-Token": token},
    )
    latest = store.latest_telemetry("PC-00000001")
    assert latest["expiresAt"], "every telemetry document needs expiresAt"
    delta = from_iso(latest["expiresAt"]) - from_iso(latest["timestamp"])
    assert delta == timedelta(days=7)


def test_cleanup_deletes_only_expired_telemetry(store, settings):
    service = CleanupService(store, settings)

    device_doc = {
        "deviceId": "PC-00000001",
        "name": "Home PC",
        "lastSeen": to_iso(utcnow()),
        "createdAt": to_iso(utcnow()),
    }
    store.create_device(device_doc)

    store.append_telemetry("PC-00000001", _sample("PC-00000001", timedelta(days=8)))
    store.append_telemetry("PC-00000001", _sample("PC-00000001", timedelta(days=6, hours=23)))
    store.append_telemetry("PC-00000001", _sample("PC-00000001", timedelta(hours=2)))

    result = service.run_once()

    assert result["ok"] is True
    assert result["deleted"] == 1
    remaining = store._telemetry["PC-00000001"]
    assert len(remaining) == 2
    assert store.get_device("PC-00000001") is not None


def test_cleanup_never_deletes_device_documents(store, settings):
    service = CleanupService(store, settings)
    for index in range(3):
        device_id = f"PC-0000000{index}"
        store.create_device(
            {
                "deviceId": device_id,
                "name": f"PC {index}",
                "lastSeen": to_iso(utcnow() - timedelta(days=30)),
                "createdAt": to_iso(utcnow() - timedelta(days=30)),
            }
        )
        store.append_telemetry(device_id, _sample(device_id, timedelta(days=9)))

    for _ in range(3):  # safe to run repeatedly
        service.run_once()

    for index in range(3):
        device_id = f"PC-0000000{index}"
        assert store.get_device(device_id) is not None
        assert store._telemetry[device_id] == []


def test_cleanup_is_idempotent(store, settings):
    service = CleanupService(store, settings)
    store.create_device(
        {"deviceId": "PC-00000001", "name": "PC", "lastSeen": to_iso(utcnow())}
    )
    store.append_telemetry("PC-00000001", _sample("PC-00000001", timedelta(days=10)))

    first = service.run_once()
    second = service.run_once()

    assert first["deleted"] == 1
    assert second["deleted"] == 0
    assert store.count_telemetry("PC-00000001") == 0


def test_cleanup_handles_pagination_and_batches(store, settings):
    settings.cleanup_batch_size = 100
    settings.cleanup_page_size = 250
    service = CleanupService(store, settings)
    store.create_device(
        {"deviceId": "PC-00000001", "name": "PC", "lastSeen": to_iso(utcnow())}
    )
    for _ in range(950):
        store.append_telemetry("PC-00000001", _sample("PC-00000001", timedelta(days=8)))

    result = service.run_once()

    assert result["deleted"] == 950
    assert result["scanned"] >= 950
    assert store.count_telemetry("PC-00000001") == 0


def test_cleanup_marks_devices_offline_and_logs_it(store, settings):
    service = CleanupService(store, settings)
    store.create_device(
        {
            "deviceId": "PC-00000001",
            "name": "Laptop",
            "online": True,
            "lastSeen": to_iso(utcnow() - timedelta(minutes=30)),
        }
    )

    result = service.run_once()

    assert result["devicesMarkedOffline"] == 1
    device = store.get_device("PC-00000001")
    assert device["online"] is False
    events = [entry["event"] for entry in store.list_logs("PC-00000001")]
    assert "agent_disconnected" in events


def test_ttl_policy_setup_is_reported(store, settings):
    service = CleanupService(store, settings)
    policy = service.setup_ttl()
    assert policy["field"] == "expiresAt"
    assert "status" in policy
    assert service.status["retentionDays"] == 7
    assert service.status["ttlPolicy"]["field"] == "expiresAt"


def test_internal_cleanup_endpoint_requires_secret(auth_client, settings):
    rejected = auth_client.post("/internal/cleanup")
    assert rejected.status_code == 401

    accepted = auth_client.post(
        "/internal/cleanup", headers={"X-Cleanup-Token": "test-cleanup-secret"}
    )
    assert accepted.status_code == 200
    assert accepted.json()["ok"] is True


def test_devices_remain_independent(auth_client, store):
    first = register_device(auth_client, "PC-00000001", "Home PC")
    second = register_device(auth_client, "PC-00000002", "Gaming PC")

    now = utcnow()
    for device_id, token, cpu in (
        ("PC-00000001", first["token"], 10.0),
        ("PC-00000002", second["token"], 90.0),
    ):
        for offset in range(3):
            auth_client.post(
                "/api/telemetry",
                json=telemetry_payload(
                    device_id, to_iso(now - timedelta(minutes=offset)), cpuUsage=cpu
                ),
                headers={"X-Device-Token": token},
            )

    series_a = auth_client.get("/api/devices/PC-00000001/telemetry?range=1h").json()
    series_b = auth_client.get("/api/devices/PC-00000002/telemetry?range=1h").json()

    assert series_a["count"] == 3
    assert series_b["count"] == 3
    assert {point["cpuUsage"] for point in series_a["points"]} == {10.0}
    assert {point["cpuUsage"] for point in series_b["points"]} == {90.0}

    # One device's token cannot write to another device.
    cross = auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000002", to_iso(now)),
        headers={"X-Device-Token": first["token"]},
    )
    assert cross.status_code == 401

    # Removing one device leaves the other intact.
    auth_client.delete("/api/devices/PC-00000001")
    assert auth_client.get("/api/devices/PC-00000002").status_code == 200
    assert store.get_device("PC-00000002") is not None
    assert store.get_device("PC-00000001") is None


def test_sensor_unavailability_is_logged(auth_client, store):
    token = register_device(auth_client)["token"]
    auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow()), cpuTemperature=61.0),
        headers={"X-Device-Token": token},
    )
    auth_client.post(
        "/api/telemetry",
        json=telemetry_payload("PC-00000001", to_iso(utcnow()), cpuTemperature=None),
        headers={"X-Device-Token": token},
    )
    events = [entry["event"] for entry in store.list_logs("PC-00000001")]
    assert "sensor_unavailable" in events


def test_store_counts_and_latest_batch(store):
    for index, device_id in enumerate(("PC-00000001", "PC-00000002", "PC-00000003")):
        store.create_device(
            {"deviceId": device_id, "name": device_id, "lastSeen": to_iso(utcnow())}
        )
        store.append_telemetry(
            device_id, _sample(device_id, timedelta(minutes=10 * (index + 1)))
        )
    latest = store.latest_telemetry_batch(["PC-00000001", "PC-00000002", "PC-00000003"])
    assert set(latest) == {"PC-00000001", "PC-00000002", "PC-00000003"}
    assert store.count_telemetry() == 3
    assert store.count_telemetry("PC-00000001") == 1
    assert isinstance(get_store(), type(store))
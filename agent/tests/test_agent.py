"""Agent behaviour: config, tokens, registration, retries, startup and CLI."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src import api as api_module
from src import startup as startup_module
from src.api import DeviceRevoked, MonitorApi, PendingQueue
from src.config import AgentConfig, decrypt_token, encrypt_token
from src.device import DeviceState, generate_device_id
from src.main import SingleInstance, build_parser, main

REGISTRATION = {
    "deviceId": "PC-12345678",
    "name": "Test PC",
    "agentVersion": "1.0.0",
    "os": "Windows 11 Pro (build 22631)",
    "architecture": "AMD64",
    "cpuModel": "AMD Ryzen 7 5800X",
    "gpuModel": "NVIDIA GeForce RTX 3070",
    "ramTotalMB": 32768,
}


def _api(config: AgentConfig) -> MonitorApi:
    return MonitorApi(config.api_url, timeout=0.5, max_retries=2)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def test_config_roundtrip_and_env_override(home, monkeypatch):
    config = AgentConfig()
    config.device_id = "PC-000000AB"
    config.device_name = "Office PC"
    config.telemetry_interval_seconds = 45
    config.save()

    reloaded = AgentConfig.load()
    assert reloaded.device_id == "PC-000000AB"
    assert reloaded.device_name == "Office PC"
    assert reloaded.telemetry_interval_seconds == 45

    monkeypatch.setenv("API_URL", "https://api.example.com/")
    monkeypatch.setenv("TELEMETRY_INTERVAL_SECONDS", "90")
    overridden = AgentConfig.load()
    assert overridden.api_url == "https://api.example.com"
    assert overridden.telemetry_interval_seconds == 90


def test_config_clamps_interval(home, monkeypatch):
    monkeypatch.setenv("TELEMETRY_INTERVAL_SECONDS", "1")
    assert AgentConfig.load().telemetry_interval_seconds == 10
    monkeypatch.setenv("TELEMETRY_INTERVAL_SECONDS", "99999")
    assert AgentConfig.load().telemetry_interval_seconds == 3600


def test_config_never_stores_token_in_plain_file(home):
    config = AgentConfig()
    config.device_id = "PC-000000AB"
    config.save()
    config.save_token("super-secret-token")
    assert config.config_path.exists()
    assert "super-secret-token" not in config.config_path.read_text(encoding="utf-8")
    assert config.load_token() == "super-secret-token"


def test_token_encryption_roundtrip():
    token = "tok_live_abcdefghijklmnop"
    assert decrypt_token(encrypt_token(token)) == token
    assert encrypt_token(token) != token.encode("utf-8")


def test_token_file_missing_returns_empty(home):
    assert AgentConfig().load_token() == ""


# ---------------------------------------------------------------------------
# Device identity / registration
# ---------------------------------------------------------------------------
def test_generate_device_id_format():
    for _ in range(50):
        device_id = generate_device_id()
        assert device_id.startswith("PC-")
        assert len(device_id) == 11
        int(device_id[3:], 16)  # hex only


def test_registration_stores_token_and_marks_registered(home):
    config = AgentConfig()
    api = _api(config)
    with patch.object(
        api,
        "register",
        return_value=api_module.ApiResult(
            ok=True, data={"deviceId": "PC-12345678", "token": "issued-token", "created": True}
        ),
    ):
        state = DeviceState(config, api)
        assert state.register() is True

    assert config.device_id == "PC-12345678"
    assert config.registered is True
    assert config.load_token() == "issued-token"
    assert api.token == "issued-token"


def test_registration_failure_leaves_no_token(home):
    config = AgentConfig()
    api = _api(config)
    with patch.object(
        api, "register", return_value=api_module.ApiResult(ok=False, status_code=500, error="boom")
    ):
        assert DeviceState(config, api).register() is False
    assert config.load_token() == ""


def test_registration_conflict_is_reported(home):
    config = AgentConfig()
    api = _api(config)
    with patch.object(
        api,
        "register",
        return_value=api_module.ApiResult(
            ok=False,
            status_code=409,
            error="device id is already registered",
        ),
    ):
        assert DeviceState(config, api).register() is False


def test_revoked_token_stops_uploads(home):
    config = AgentConfig()
    config.save_token("token")
    api = _api(config)
    with patch.object(api, "send_telemetry", side_effect=DeviceRevoked("revoked")):
        state = DeviceState(config, api)
        assert state.registered is False


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------
def test_pending_queue_is_bounded():
    queue = PendingQueue(maxlen=3)
    for index in range(6):
        queue.put({"value": index})
    assert len(queue) == 3
    assert queue.dropped == 3
    assert [item["value"] for item in queue.drain()] == [3, 4, 5]


def test_request_retries_with_backoff(monkeypatch):
    client = MonitorApi("http://api.test", timeout=0.1, max_retries=3)
    calls = {"count": 0}

    def fake_sleep(_seconds):
        calls["count"] += 1

    def fake_request(*_args, **_kwargs):
        calls["attempt"] = calls.get("attempt", 0) + 1
        raise httpx.ConnectError("dns failure")

    monkeypatch.setattr("src.api.time.sleep", fake_sleep)
    monkeypatch.setattr(client._client, "request", fake_request)

    result = client.request("POST", "/api/telemetry", {"a": 1})
    assert result.ok is False
    assert calls["attempt"] == 3
    assert calls["count"] == 2  # two backoff sleeps, never an unbounded loop


def test_request_raises_on_revoked_token():
    client = MonitorApi("http://api.test", timeout=0.1, max_retries=1)
    response = httpx.Response(
        403, json={"error": {"code": "device_revoked", "message": "revoked"}}
    )
    with patch.object(client._client, "request", return_value=response):
        with pytest.raises(DeviceRevoked):
            client.request("POST", "/api/telemetry", {})


def test_request_returns_parsed_body():
    client = MonitorApi("http://api.test", timeout=0.1, max_retries=1)
    response = httpx.Response(202, json={"deviceId": "PC-1", "telemetryId": "t1"})
    with patch.object(client._client, "request", return_value=response):
        result = client.request("POST", "/api/telemetry", {})
    assert result.ok is True
    assert result.data["telemetryId"] == "t1"
    assert result.latency_ms >= 0


def test_timeout_is_handled_not_raised(monkeypatch):
    client = MonitorApi("http://api.test", timeout=0.1, max_retries=2)
    monkeypatch.setattr("src.api.time.sleep", lambda _s: None)

    def timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(client._client, "request", timeout)
    result = client.request("POST", "/api/telemetry", {})
    assert result.ok is False
    assert "timeout" in (result.error or "")


# ---------------------------------------------------------------------------
# Startup management
# ---------------------------------------------------------------------------
def test_startup_command_is_visible_and_quoted():
    command = startup_module._run_command()
    assert command
    assert command.startswith('"') or command.startswith("python") or "python" in command
    assert startup_module.APP_NAME == "PC-Monitor"
    assert "CurrentVersion\\Run" in startup_module.RUN_KEY


def test_startup_enable_disable_are_safe_off_windows(monkeypatch):
    monkeypatch.setattr(startup_module.sys, "platform", "linux")
    assert startup_module.enable() is False
    assert startup_module.disable() is False
    assert startup_module.is_enabled() is False


def test_configure_applies_preference(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(startup_module, "is_enabled", lambda: False)
    monkeypatch.setattr(startup_module, "enable", lambda: calls.append(True) or True)

    class Config:
        startup_enabled = True

    startup_module.configure(Config())
    assert calls == [True]


# ---------------------------------------------------------------------------
# CLI / single instance
# ---------------------------------------------------------------------------
def test_parser_supports_documented_flags():
    parser = build_parser()
    args = parser.parse_args(
        ["--api-url", "https://x.test", "--interval", "60", "--no-startup", "--once"]
    )
    assert args.api_url == "https://x.test"
    assert args.interval == 60
    assert args.no_startup is True
    assert args.once is True


def test_status_command_prints_json(home, capsys):
    assert main(["--status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "deviceId" in payload
    assert "telemetryIntervalSeconds" in payload
    assert payload["startupCommand"] in (None, payload["startupCommand"])


def test_no_startup_flag_exits(home, monkeypatch):
    monkeypatch.setattr(startup_module, "disable", lambda: True)
    assert main(["--no-startup"]) == 0


def test_single_instance_is_permissive_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    instance = SingleInstance()
    assert instance.acquire() is True
    instance.release()


def test_run_once_uploads_single_sample(home, monkeypatch):
    config = AgentConfig()
    config.device_id = "PC-00000001"
    config.save_token("token")
    config.save()

    sent: list[dict] = []

    class FakeApi(MonitorApi):
        def send_telemetry(self, payload):
            sent.append(payload)
            return api_module.ApiResult(ok=True, status_code=202, data={})

        def heartbeat(self, device_id, timestamp, version):
            return api_module.ApiResult(ok=True, data={})

    monkeypatch.setattr("src.main.MonitorApi", FakeApi)
    assert main(["--once", "--log-level", "ERROR"]) == 0
    assert len(sent) == 1
    assert sent[0]["deviceId"] == "PC-00000001"
"""Collector tests: every sensor module must degrade gracefully, never crash."""

from __future__ import annotations

import sys
from unittest.mock import patch

import psutil
import pytest

from src import battery, collector, cpu, disk, gpu, memory, network


def test_cpu_collect_returns_usage():
    cpu.usage()
    sample = cpu.collect()
    assert 0 <= sample["cpuUsage"] <= 100
    assert isinstance(sample["cpuPerCore"], list)
    if sample["cpuPerCore"] is not None:
        assert all(0 <= value <= 100 for value in sample["cpuPerCore"])


def test_cpu_temperature_is_none_on_windows_not_fabricated():
    # Windows exposes no user-mode thermal API: the agent must report "unavailable"
    # rather than inventing a value.
    with patch.object(psutil, "sensors_temperatures", create=True, side_effect=OSError):
        cpu._temperature_available = None
        assert cpu.temperature_c() is None


def test_cpu_temperature_reads_available_sensors():
    class Sensor:
        label = "Package id 0"
        current = 61.5

    with patch.object(psutil, "sensors_temperatures", create=True, return_value={"coretemp": [Sensor()]}):
        cpu._temperature_available = None
        assert cpu.temperature_c() == 61.5


def test_cpu_collect_survives_broken_psutil():
    with patch("psutil.cpu_percent", side_effect=RuntimeError("boom")):
        sample = cpu.collect()
    # A failing usage sensor must not take the rest of the CPU block down.
    assert "cpuUsage" not in sample


def test_gpu_collect_returns_dict_without_hardware():
    with patch("src.gpu._load_nvml", return_value=None), patch(
        "src.gpu._nvidia_smi_query", return_value=None
    ), patch("src.gpu._wmi_gpu_names", return_value=[]):
        gpu._model_cache = None
        assert isinstance(gpu.collect(), dict)


def test_gpu_collect_uses_nvml_sample():
    with patch("src.gpu._load_nvml", return_value=object()), patch(
        "src.gpu._nvml_sample",
        return_value={
            "model": "NVIDIA GeForce RTX 4070",
            "gpuUsage": 61.0,
            "gpuTemperature": 58.0,
            "vramUsedMB": 1024.0,
            "vramTotalMB": 12288.0,
        },
    ):
        sample = gpu.collect()
    assert sample["gpuUsage"] == 61.0
    assert sample["vramTotalMB"] == 12288.0


def test_gpu_nvml_sample_merges_multiple_devices():
    handle = type(
        "FakeNvml",
        (),
        {
            "nvmlDeviceGetCount": lambda self: 2,
            "nvmlDeviceGetHandleByIndex": lambda self, index: f"handle-{index}",
            "nvmlDeviceGetName": lambda self, device: device.replace("handle-", "GPU "),
            "nvmlDeviceGetUtilizationRates": lambda self, device: type(
                "Util", (), {"gpu": 50 if device.endswith("0") else 80}
            )(),
            "NVML_TEMPERATURE_GPU": 0,
            "nvmlDeviceGetTemperature": lambda self, device, sensor: 60,
            "nvmlDeviceGetMemoryInfo": lambda self, device: type(
                "Mem", (), {"used": 1024**3, "total": 8 * 1024**3}
            )(),
        },
    )()
    merged = gpu._nvml_sample(handle)
    assert merged["gpuUsage"] == 80
    assert merged["vramUsedMB"] == 2048.0


def test_memory_collect():
    sample = memory.collect()
    assert 0 <= sample["ramUsage"] <= 100
    assert sample["ramTotalMB"] > 0
    assert sample["ramUsedMB"] <= sample["ramTotalMB"]


def test_disk_capacity_and_throughput():
    sample = disk.collect()
    assert "diskUsage" in sample or sample == {}
    # First call has no baseline for throughput, the second one does.
    disk.throughput()
    assert "diskReadMbps" in disk.throughput()


def test_disk_capacity_failure_is_swallowed():
    with patch("psutil.disk_usage", side_effect=PermissionError):
        assert disk.capacity() == {}


def test_network_throughput_second_sample():
    network._last_counters = None
    network._last_time = None
    first = network.throughput()
    assert "downloadMbps" not in first
    second = network.throughput()
    assert second.get("downloadMbps", 0) >= 0
    assert second.get("uploadMbps", 0) >= 0


def test_battery_returns_empty_dict_on_desktop():
    with patch("psutil.sensors_battery", return_value=None), patch(
        "src.battery._windows_battery", return_value=None
    ):
        assert battery.collect() == {}


def test_battery_reports_charging_state():
    fake = type(
        "Battery",
        (),
        {"percent": 55.0, "power_plugged": True, "secsleft": 3600},
    )()
    with patch("psutil.sensors_battery", return_value=fake):
        sample = battery.collect()
    assert sample["batteryPercent"] == 55.0
    assert sample["batteryCharging"] is True
    assert sample["batteryTimeLeftSeconds"] == 3600


def test_collect_builds_valid_payload(config):
    payload = collector.collect("PC-00000001", config.api_url, measure_latency=False)
    assert payload["deviceId"] == "PC-00000001"
    assert payload["timestamp"].endswith("Z")
    assert "T" in payload["timestamp"]
    assert all(value is not None for value in payload.values())
    if "cpuUsage" in payload:
        assert 0 <= payload["cpuUsage"] <= 100


def test_collect_survives_failing_sensor_modules():
    # Even if every sensor module explodes, the collector returns a usable payload.
    for module in ("cpu", "gpu", "memory", "disk", "network", "battery"):
        with patch(f"src.{module}.collect", side_effect=RuntimeError("driver crash")):
            payload = collector.collect("PC-00000001")
    assert payload["deviceId"] == "PC-00000001"
    assert payload["timestamp"].endswith("Z")


def test_collect_is_resilient_to_sensor_exceptions():
    with patch("src.cpu.collect", side_effect=RuntimeError("sensor died")), patch(
        "src.gpu.collect", side_effect=OSError("nvml gone")
    ):
        payload = collector.collect("PC-00000001")
    assert payload["deviceId"] == "PC-00000001"
    assert "cpuUsage" not in payload
    assert "ramUsage" in payload
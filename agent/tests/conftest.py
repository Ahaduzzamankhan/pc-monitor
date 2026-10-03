"""Agent test fixtures - every test runs against a temporary config directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

os.environ["PC_MONITOR_HOME"] = str(Path(os.environ.get("TEMP", "/tmp")) / "pc-monitor-tests")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point the agent's config directory at a temporary folder."""
    directory = tmp_path / "PC-Monitor"
    directory.mkdir()
    monkeypatch.setenv("PC_MONITOR_HOME", str(directory))
    from src.logger import configure_logging

    configure_logging("DEBUG", console=False)
    return directory


@pytest.fixture
def config(home):
    from src.config import AgentConfig

    instance = AgentConfig()
    instance.api_url = "http://127.0.0.1:9"  # closed port: fast failure path
    instance.save()
    return instance
"""HTTP client for the PC Monitor API.

Resilience rules:

* Exponential backoff with a bounded number of retries.
* Every request carries the device token; a rejected token (401/403) marks the
  device as *revoked* and stops uploads instead of re-registering silently.
* Only a small, bounded in-memory queue is kept when the backend is
  unreachable - the agent never grows an unlimited local backlog.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Optional

import httpx

from src.logger import get_logger

logger = get_logger()

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0
MAX_QUEUED_SAMPLES = 20


class DeviceRevoked(Exception):
    """Raised when the backend rejects the stored device token."""

    def __init__(self, message: str, status_code: int = 401, code: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code

    @property
    def explicitly_revoked(self) -> bool:
        """True when the device was removed on the dashboard (403)."""
        return self.status_code == 403 or self.code == "device_revoked"


class PendingQueue:
    """Bounded FIFO of telemetry samples waiting for connectivity."""

    def __init__(self, maxlen: int = MAX_QUEUED_SAMPLES) -> None:
        self._items: Deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.dropped = 0

    def put(self, sample: dict[str, Any]) -> None:
        if len(self._items) == self._items.maxlen:
            self.dropped += 1
            logger.warning("queue_full", "dropping oldest sample (backend unreachable)")
        self._items.append(sample)

    def drain(self) -> list[dict[str, Any]]:
        items = list(self._items)
        self._items.clear()
        return items

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class ApiResult:
    ok: bool
    status_code: Optional[int] = None
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    latency_ms: float = 0.0


class MonitorApi:
    """Thin client around the three agent endpoints."""

    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "PC-Monitor-Agent/1.0"},
            follow_redirects=False,
        )
        self.pending = PendingQueue()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover
            pass

    def set_token(self, token: str) -> None:
        self.token = token

    # -- transport ---------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Device-Token"] = self.token
        return headers

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[dict[str, Any]] = None,
        retry: bool = True,
    ) -> ApiResult:
        """Perform one HTTP call with bounded exponential backoff."""
        attempts = self.max_retries if retry else 1
        delay = BACKOFF_BASE_SECONDS
        result = ApiResult(ok=False, error="not attempted")

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                response = self._client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
            except httpx.TimeoutException as exc:
                result = ApiResult(ok=False, error=f"timeout: {exc}")
                logger.warning("api_timeout", "request timed out", path=path, attempt=attempt)
            except httpx.TransportError as exc:
                # DNS failure, connection refused, TLS error, ...
                result = ApiResult(ok=False, error=f"network error: {exc}")
                logger.warning(
                    "api_network_error",
                    "backend unreachable",
                    path=path,
                    attempt=attempt,
                    error=str(exc),
                )
            else:
                latency = round((time.perf_counter() - started) * 1000, 2)
                if response.status_code in (200, 201, 202):
                    try:
                        data = response.json() if response.content else {}
                    except ValueError:
                        data = {}
                    return ApiResult(ok=True, status_code=response.status_code, data=data, latency_ms=latency)
                if response.status_code in (401, 403):
                    message = _error_message(response)
                    code = _error_code(response)
                    logger.error(
                        "api_rejected",
                        "device token rejected - uploads stopped",
                        path=path,
                        status=response.status_code,
                        code=code,
                        error=message,
                    )
                    raise DeviceRevoked(message, status_code=response.status_code, code=code)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "5") or 5)
                    result = ApiResult(ok=False, status_code=429, error="rate limited")
                    logger.warning("api_rate_limited", "slowing down", retryAfter=retry_after)
                    delay = max(delay, float(retry_after))
                elif 400 <= response.status_code < 500:
                    result = ApiResult(
                        ok=False,
                        status_code=response.status_code,
                        error=_error_message(response),
                    )
                    logger.warning("api_client_error", "request rejected", status=response.status_code)
                    if result.status_code not in (408, 425, 429):
                        return result  # not worth retrying
                elif response.status_code >= 500:
                    result = ApiResult(ok=False, status_code=response.status_code, error="server error")
                    logger.warning("api_server_error", "server error", status=response.status_code)
                else:  # pragma: no cover - unexpected
                    result = ApiResult(ok=False, status_code=response.status_code, error="unexpected response")

            if attempt < attempts:
                time.sleep(min(delay, BACKOFF_MAX_SECONDS))
                delay *= 2

        return result

    # -- endpoints ---------------------------------------------------------
    def register(self, payload: dict[str, Any], token: Optional[str] = None) -> ApiResult:
        """Register this agent and receive the device token."""
        if token:
            self.token = token
        return self.request("POST", "/api/devices/register", payload)

    def heartbeat(self, device_id: str, timestamp: str, agent_version: str) -> ApiResult:
        return self.request(
            "POST",
            "/api/devices/heartbeat",
            {
                "deviceId": device_id,
                "timestamp": timestamp,
                "agentVersion": agent_version,
            },
        )

    def send_telemetry(self, payload: dict[str, Any]) -> ApiResult:
        return self.request("POST", "/api/telemetry", payload)

    def check_health(self) -> ApiResult:
        return self.request("GET", "/health", retry=False)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or response.status_code)
    return f"HTTP {response.status_code}"


def _error_code(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("code") or "")
    return ""
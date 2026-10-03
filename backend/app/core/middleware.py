"""ASGI middleware: payload limits, rate limiting and security headers.

Implemented as plain ASGI3 middleware (no ``BaseHTTPMiddleware``) so it works
unchanged on every Starlette release FastAPI ships with.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Deque, MutableMapping

from app.core.config import Settings, get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class SlidingWindowLimiter:
    """In-process sliding window rate limiter.

    Suitable for a single-instance deployment (the common case for a personal
    monitoring platform).  Replace this class with a Redis-backed implementation
    if the backend is scaled horizontally.
    """

    def __init__(self, window_seconds: int = 60) -> None:
        self.window = window_seconds
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._last_prune = 0.0

    def check(self, key: str, limit: int, window_seconds: int | None = None) -> tuple[bool, int, int]:
        """Return ``(allowed, remaining, retry_after_seconds)``."""
        now = time.monotonic()
        window = window_seconds or self.window
        bucket = self._hits[key]
        cutoff = now - window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(bucket[0] + window - now) + 1)
            return False, 0, retry_after
        bucket.append(now)
        self._maybe_prune(now)
        return True, limit - len(bucket), 0

    def _maybe_prune(self, now: float) -> None:
        if now - self._last_prune < 60:
            return
        self._last_prune = now
        cutoff = now - self.window
        for key in list(self._hits):
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()
        self._last_prune = 0.0


limiter = SlidingWindowLimiter()


async def send_json(
    send: Send, status_code: int, payload: dict[str, Any], headers: dict[str, str] | None = None
) -> None:
    body = _dumps(payload).encode("utf-8")
    raw_headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("latin-1"), str(value).encode("latin-1")))
    await send({"type": "http.response.start", "status": status_code, "headers": raw_headers})
    await send({"type": "http.response.body", "body": body})


def _dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload)


class BodySizeLimitMiddleware:
    """Reject oversized request bodies before a handler ever sees them."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        if scope.get("method") in {"POST", "PUT", "PATCH"}:
            declared = headers.get("content-length")
            if declared is not None:
                try:
                    length = int(declared)
                except ValueError:
                    await send_json(
                        send,
                        400,
                        {"error": {"code": "invalid_content_length", "message": "bad content-length"}},
                    )
                    return
                if length > self.max_bytes:
                    await send_json(
                        send,
                        413,
                        {
                            "error": {
                                "code": "payload_too_large",
                                "message": f"request body exceeds {self.max_bytes} bytes",
                            }
                        },
                    )
                    return
        await self.app(scope, receive, send)


class RateLimitMiddleware:
    """Per-route request limiting for agent and dashboard endpoints."""

    AGENT_RULES: tuple[tuple[str, str, str, int], ...] = (
        # (method, path, settings attribute, window seconds)
        ("POST", "/api/telemetry", "rate_limit_telemetry_per_minute", 60),
        ("POST", "/api/devices/heartbeat", "rate_limit_heartbeat_per_minute", 60),
        ("POST", "/api/devices/register", "rate_limit_register_per_hour", 3600),
    )

    def __init__(self, app, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    @staticmethod
    def _client_key(scope: Scope) -> str:
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client = scope.get("client") or ("unknown", 0)
            client_ip = client[0]
        agent_key = headers.get("x-device-token") or headers.get("authorization") or ""
        return f"{client_ip}:{hash(agent_key) & 0xFFFFFF:06x}"

    def _resolve(self, scope: Scope) -> tuple[int, int] | None:
        path = scope.get("path", "/").rstrip("/") or "/"
        method = scope.get("method", "GET")
        for rule_method, rule_path, attribute, window in self.AGENT_RULES:
            if method == rule_method and path == rule_path:
                return int(getattr(self.settings, attribute)), window
        public_paths = ("/api/auth/", "/api/health", "/health")
        if path.startswith("/api/") and not any(path.startswith(item) for item in public_paths):
            return int(self.settings.rate_limit_dashboard_per_minute), 60
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rule = self._resolve(scope)
        if rule is None:
            await self.app(scope, receive, send)
            return
        limit, window = rule
        key = f"{scope.get('path')}:{self._client_key(scope)}"
        allowed, _remaining, retry_after = limiter.check(key, limit, window)
        if not allowed:
            logger.warning(
                "rate_limited",
                "request rejected by rate limiter",
                path=scope.get("path"),
                limit=limit,
                window=window,
            )
            await send_json(
                send,
                429,
                {"error": {"code": "rate_limited", "message": "too many requests"}},
                headers={"Retry-After": str(retry_after)},
            )
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Adds conservative security headers to every response."""

    HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-resource-policy", b"same-site"),
        (b"cache-control", b"no-store"),
    )

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                for key, value in self.HEADERS:
                    if key not in existing:
                        headers.append((key, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def install_middleware(app, settings: Settings | None = None) -> None:
    """Install the middleware stack on a FastAPI application."""
    settings = settings or get_settings()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware, settings=settings)
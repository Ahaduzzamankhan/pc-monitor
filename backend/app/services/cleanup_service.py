"""Retention and housekeeping.

Two independent mechanisms keep the database small:

* **Firestore TTL** on the ``expiresAt`` field (enabled at startup when the
  project supports it - this is the preferred path).
* **This service** as the portable fallback: a scheduled job that deletes
  expired telemetry documents in batches with pagination, and flags devices
  that have gone silent.

The job runs inside the backend process, so deletion never depends on a
Windows PC being online.  It is safe to run repeatedly and it never deletes
device documents.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from app.core.config import Settings, get_settings
from app.core.firebase import BaseStore, get_store
from app.services.device_service import DeviceService, reset_device_service
from app.utils.logging import get_logger
from app.utils.time import to_iso, utcnow

logger = get_logger(__name__)


class CleanupService:
    def __init__(
        self,
        store: Optional[BaseStore] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._store = store or get_store()
        self._settings = settings or get_settings()
        self._devices = DeviceService(self._store, self._settings)
        self._last_run_at: Optional[datetime] = None
        self._last_result: Optional[dict[str, Any]] = None
        self._ttl_policy: dict[str, Any] = {"status": "unknown"}
        self._errors = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    @property
    def ttl_policy(self) -> dict[str, Any]:
        return dict(self._ttl_policy)

    @property
    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "retentionDays": self._settings.telemetry_retention_days,
            "ttlPolicy": dict(self._ttl_policy),
            "lastRunAt": to_iso(self._last_run_at),
            "lastRunResult": dict(self._last_result) if self._last_result else None,
            "totalErrors": self._errors,
        }

    def setup_ttl(self) -> dict[str, Any]:
        """Try to register the Firestore TTL policy; never fatal."""
        try:
            self._ttl_policy = self._store.ensure_ttl_policy()
            logger.info(
                "ttl_policy",
                "Firestore TTL policy status",
                status=self._ttl_policy.get("status"),
                field=self._ttl_policy.get("field"),
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._errors += 1
            self._ttl_policy = {"status": "error", "detail": str(exc)}
            logger.error("ttl_policy_failed", "TTL setup failed", error=str(exc))
        return self._ttl_policy

    def run_once(self, now: Optional[datetime] = None) -> dict[str, Any]:
        """Delete expired telemetry and refresh offline status."""
        started = utcnow()
        now = now or started
        result: dict[str, Any] = {"startedAt": to_iso(started)}
        try:
            deletion = self._store.delete_expired_telemetry(
                now=now,
                batch_size=self._settings.cleanup_batch_size,
                page_size=self._settings.cleanup_page_size,
                max_pages=self._settings.cleanup_max_pages_per_run,
            )
            result.update(deletion)
            result["devicesMarkedOffline"] = len(self._devices.mark_offline_devices())
            result["ok"] = True
            if deletion.get("deleted"):
                logger.info(
                    "cleanup_deleted",
                    "expired telemetry removed",
                    deleted=deletion.get("deleted"),
                    pages=deletion.get("pages"),
                    batches=deletion.get("batches"),
                )
        except Exception as exc:
            self._errors += 1
            result["ok"] = False
            result["error"] = str(exc)
            logger.error("cleanup_failed", "cleanup pass failed", error=str(exc))
        result["finishedAt"] = to_iso(utcnow())
        self._last_run_at = started
        self._last_result = result
        return result

    async def run_locked(self) -> dict[str, Any]:
        """Async wrapper: serialises passes and keeps Firestore calls off the loop."""
        async with self._lock:
            return await asyncio.to_thread(self.run_once)


class CleanupScheduler:
    """Background task started by the FastAPI lifespan handler."""

    def __init__(self, service: CleanupService, interval_minutes: int) -> None:
        self._service = service
        self._interval = max(1, interval_minutes) * 60
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="pc-monitor-cleanup")
        logger.info("cleanup_scheduled", "retention cleanup scheduled", intervalSeconds=self._interval)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown path
            pass
        self._task = None

    async def _loop(self) -> None:
        # Small delay so application startup is not blocked by the first pass.
        await asyncio.sleep(2)
        while not self._stopping.is_set():
            try:
                await self._service.run_locked()
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("cleanup_loop_error", "cleanup loop iteration failed", error=str(exc))
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue


_scheduler: Optional[CleanupScheduler] = None
_service_singleton: Optional[CleanupService] = None


def get_cleanup_service() -> CleanupService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = CleanupService()
    return _service_singleton


def get_scheduler() -> Optional[CleanupScheduler]:
    return _scheduler


def start_scheduler(service: CleanupService, interval_minutes: int) -> CleanupScheduler:
    global _scheduler
    _scheduler = CleanupScheduler(service, interval_minutes)
    _scheduler.start()
    return _scheduler


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        await _scheduler.stop()
        _scheduler = None


def reset_cleanup_service() -> None:
    """Test helper."""
    global _service_singleton
    _service_singleton = None
    reset_device_service()
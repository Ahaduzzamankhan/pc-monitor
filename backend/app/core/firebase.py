"""Firestore access layer.

Only the backend ever talks to Firestore - the browser and the Windows agent
never receive Firebase Admin credentials.

Two implementations of the same interface live here:

``FirestoreStore``
    Production storage on Google Cloud Firestore (Firebase project).
``InMemoryStore``
    A dependency free store used for local development and the test suite so
    the whole API can be exercised without network access.

Timestamps are stored as native ``datetime`` values (required for Firestore TTL
policies) and are always returned to callers as ISO-8601 UTC strings.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Iterable, Optional

from app.core.config import Settings, get_settings
from app.utils.logging import get_logger
from app.utils.time import ensure_utc, to_iso

logger = get_logger(__name__)

DEVICES_COLLECTION = "devices"
TELEMETRY_COLLECTION = "telemetry"
LOGS_COLLECTION = "logs"
REVOKED_COLLECTION = "revoked_devices"
TTL_FIELD = "expiresAt"


def _to_datetime(value: Any) -> Any:
    """ISO string -> aware datetime (Firestore timestamps are datetimes)."""
    if isinstance(value, str):
        try:
            return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return value
    return value


def _from_datetime(value: Any) -> Any:
    """datetime -> ISO string; every other value passes through untouched."""
    if isinstance(value, datetime):
        return to_iso(value)
    return value


class BaseStore(ABC):
    """Storage contract used by the service layer."""

    # -- devices ----------------------------------------------------------
    @abstractmethod
    def create_device(self, device: dict[str, Any]) -> dict[str, Any]:
        """Create (or overwrite) a device document."""

    @abstractmethod
    def get_device(self, device_id: str) -> Optional[dict[str, Any]]:
        ...

    @abstractmethod
    def list_devices(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def update_device(self, device_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
        ...

    @abstractmethod
    def delete_device(self, device_id: str) -> bool:
        """Delete a device document *and* its telemetry/log subcollections."""

    @abstractmethod
    def record_revocation(self, device_id: str, reason: str, revoked_at: datetime) -> None:
        ...

    @abstractmethod
    def is_revoked(self, device_id: str) -> bool:
        ...

    @abstractmethod
    def clear_revocation(self, device_id: str) -> None:
        """Allow a removed device id to be registered again."""

    # -- telemetry --------------------------------------------------------
    @abstractmethod
    def append_telemetry(self, device_id: str, document: dict[str, Any]) -> str:
        ...

    @abstractmethod
    def list_telemetry(
        self,
        device_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return telemetry samples between ``start`` and ``end`` (ascending)."""

    @abstractmethod
    def latest_telemetry(self, device_id: str) -> Optional[dict[str, Any]]:
        ...

    @abstractmethod
    def latest_telemetry_batch(
        self, device_ids: list[str], max_docs: int = 300
    ) -> dict[str, dict[str, Any]]:
        """Latest sample per device using a single query (dashboard friendly)."""

    @abstractmethod
    def count_telemetry(self, device_id: Optional[str] = None) -> int:
        ...

    @abstractmethod
    def delete_expired_telemetry(
        self,
        now: datetime,
        batch_size: int = 400,
        page_size: int = 200,
        max_pages: int = 50,
    ) -> dict[str, int]:
        """Delete expired telemetry documents in batches. Never touches devices."""

    # -- logs -------------------------------------------------------------
    @abstractmethod
    def append_log(
        self,
        device_id: str,
        event: str,
        level: str = "info",
        message: str = "",
        data: Optional[dict[str, Any]] = None,
    ) -> str:
        ...

    @abstractmethod
    def list_logs(
        self, device_id: Optional[str], limit: int = 100
    ) -> list[dict[str, Any]]:
        ...

    # -- retention --------------------------------------------------------
    @abstractmethod
    def ensure_ttl_policy(self, ttl_field: str = TTL_FIELD) -> dict[str, Any]:
        """Best effort: register a Firestore TTL policy for ``ttl_field``."""


class InMemoryStore(BaseStore):
    """Thread safe in-process store used for tests and local development."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, dict[str, Any]] = {}
        self._telemetry: dict[str, list[dict[str, Any]]] = {}
        self._logs: dict[str, list[dict[str, Any]]] = {}
        self._revoked: dict[str, dict[str, Any]] = {}
        self._seq = 0

    # -- helpers ----------------------------------------------------------
    def _next_id(self) -> str:
        self._seq += 1
        return f"mem-{self._seq:08d}"

    @staticmethod
    def _prepare_write(document: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (_to_datetime(value) if isinstance(value, str) else value)
            for key, value in document.items()
        }

    @staticmethod
    def _prepare_read(document: dict[str, Any]) -> dict[str, Any]:
        return {key: _from_datetime(value) for key, value in document.items()}

    # -- devices ----------------------------------------------------------
    def create_device(self, device: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._devices[device["deviceId"]] = self._prepare_write(dict(device))
            self._telemetry.setdefault(device["deviceId"], [])
            self._logs.setdefault(device["deviceId"], [])
            return self._prepare_read(self._devices[device["deviceId"]])

    def get_device(self, device_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            device = self._devices.get(device_id)
            return self._prepare_read(dict(device)) if device else None

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            devices = [self._prepare_read(dict(d)) for d in self._devices.values()]
        devices.sort(key=lambda item: item.get("lastSeen") or "", reverse=True)
        return devices

    def update_device(self, device_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                return None
            device.update(self._prepare_write(dict(patch)))
            return self._prepare_read(dict(device))

    def delete_device(self, device_id: str) -> bool:
        with self._lock:
            existed = self._devices.pop(device_id, None) is not None
            self._telemetry.pop(device_id, None)
            self._logs.pop(device_id, None)
            return existed

    def record_revocation(self, device_id: str, reason: str, revoked_at: datetime) -> None:
        with self._lock:
            self._revoked[device_id] = {"reason": reason, "revokedAt": revoked_at}

    def is_revoked(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._revoked

    def clear_revocation(self, device_id: str) -> None:
        with self._lock:
            self._revoked.pop(device_id, None)

    # -- telemetry --------------------------------------------------------
    def append_telemetry(self, device_id: str, document: dict[str, Any]) -> str:
        with self._lock:
            doc_id = document.get("telemetryId") or self._next_id()
            stored = self._prepare_write({**document, "telemetryId": doc_id})
            self._telemetry.setdefault(device_id, []).append(stored)
            return doc_id

    def list_telemetry(
        self, device_id: str, start: datetime, end: datetime, limit: int
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                doc
                for doc in self._telemetry.get(device_id, [])
                if isinstance(doc.get("timestamp"), datetime)
                and start <= doc["timestamp"] <= end
            ]
        rows.sort(key=lambda item: item["timestamp"])
        if len(rows) > limit:
            # Keep a uniform sample across the window instead of the head only.
            step = len(rows) / limit
            rows = [rows[int(index * step)] for index in range(limit)]
        return [self._prepare_read(dict(row)) for row in rows]

    def latest_telemetry(self, device_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            rows = [
                doc
                for doc in self._telemetry.get(device_id, [])
                if isinstance(doc.get("timestamp"), datetime)
            ]
        if not rows:
            return None
        rows.sort(key=lambda item: item["timestamp"])
        return self._prepare_read(dict(rows[-1]))

    def latest_telemetry_batch(
        self, device_ids: list[str], max_docs: int = 300
    ) -> dict[str, dict[str, Any]]:
        wanted = set(device_ids)
        with self._lock:
            rows = [
                self._prepare_read(dict(row))
                for owner, samples in self._telemetry.items()
                if owner in wanted
                for row in samples
            ]
        rows.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            owner = row.get("deviceId")
            if owner in wanted and owner not in latest:
                latest[owner] = row
        return latest

    def count_telemetry(self, device_id: Optional[str] = None) -> int:
        with self._lock:
            if device_id is not None:
                return len(self._telemetry.get(device_id, []))
            return sum(len(rows) for rows in self._telemetry.values())

    def delete_expired_telemetry(
        self,
        now: datetime,
        batch_size: int = 400,
        page_size: int = 200,
        max_pages: int = 50,
    ) -> dict[str, int]:
        deleted = 0
        scanned = 0
        with self._lock:
            for device_id, rows in self._telemetry.items():
                remaining = [
                    row
                    for row in rows
                    if not (
                        isinstance(row.get("expiresAt"), datetime) and row["expiresAt"] <= now
                    )
                ]
                deleted += len(rows) - len(remaining)
                scanned += len(rows)
                self._telemetry[device_id] = remaining
        return {"deleted": deleted, "scanned": scanned, "pages": 1, "batches": 1 if deleted else 0}

    # -- logs -------------------------------------------------------------
    def append_log(
        self,
        device_id: str,
        event: str,
        level: str = "info",
        message: str = "",
        data: Optional[dict[str, Any]] = None,
    ) -> str:
        from app.utils.time import utcnow

        with self._lock:
            log_id = self._next_id()
            entry = {
                "logId": log_id,
                "deviceId": device_id,
                "event": event,
                "level": level,
                "message": message,
                "data": data or {},
                "timestamp": utcnow(),
            }
            self._logs.setdefault(device_id, []).append(entry)
            return log_id

    def list_logs(self, device_id: Optional[str], limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            if device_id:
                rows = list(self._logs.get(device_id, []))
            else:
                rows = [row for rows in self._logs.values() for row in rows]
        rows.sort(key=lambda item: item.get("timestamp") or datetime.min, reverse=True)
        return [self._prepare_read(dict(row)) for row in rows[:limit]]

    # -- retention --------------------------------------------------------
    def ensure_ttl_policy(self, ttl_field: str = TTL_FIELD) -> dict[str, Any]:
        return {
            "supported": False,
            "status": "simulated",
            "field": ttl_field,
            "detail": "in-memory store always drops expired samples on read/write",
        }


class FirestoreStore(BaseStore):
    """Production store backed by Google Cloud Firestore."""

    def __init__(self, settings: Settings) -> None:
        import firebase_admin
        from firebase_admin import firestore

        if firebase_admin._apps:  # pragma: no cover - process wide singleton
            app = firebase_admin.get_app()
        elif settings.google_application_credentials:
            app = firebase_admin.initialize_app(
                firebase_admin.credentials.Certificate(
                    settings.google_application_credentials
                ),
                {"projectId": settings.firebase_project_id},
            )
        else:
            app = firebase_admin.initialize_app(
                firebase_admin.credentials.ApplicationDefault(),
                {"projectId": settings.firebase_project_id},
            )
        self._settings = settings
        self._client = firestore.client(app=app)
        self._database_id = settings.firestore_database

    # -- helpers ----------------------------------------------------------
    @property
    def _devices_ref(self):  # type: ignore[no-untyped-def]
        return self._client.collection(DEVICES_COLLECTION)

    def _device_ref(self, device_id: str):  # type: ignore[no-untyped-def]
        return self._devices_ref.document(device_id)

    @staticmethod
    def _prepare_write(document: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (_to_datetime(value) if isinstance(value, str) else value)
            for key, value in document.items()
        }

    @staticmethod
    def _prepare_read(document: dict[str, Any]) -> dict[str, Any]:
        return {key: _from_datetime(value) for key, value in document.items()}

    # -- devices ----------------------------------------------------------
    def create_device(self, device: dict[str, Any]) -> dict[str, Any]:
        self._device_ref(device["deviceId"]).set(self._prepare_write(dict(device)))
        return self._prepare_read(dict(device))

    def get_device(self, device_id: str) -> Optional[dict[str, Any]]:
        from app.utils.time import from_iso

        snapshot = self._device_ref(device_id).get()
        if not snapshot.exists:
            return None
        device = self._prepare_read(dict(snapshot.to_dict() or {}))
        # Firestore may return naive datetimes depending on emulator behaviour.
        last_seen = from_iso(device.get("lastSeen"))
        if last_seen is not None:
            device["lastSeen"] = to_iso(last_seen)
        return device

    def list_devices(self) -> list[dict[str, Any]]:
        devices = [
            self._prepare_read(dict(doc.to_dict() or {})) for doc in self._devices_ref.stream()
        ]
        devices.sort(key=lambda item: item.get("lastSeen") or "", reverse=True)
        return devices

    def update_device(self, device_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
        ref = self._device_ref(device_id)
        if not ref.get().exists:
            return None
        ref.update(self._prepare_write(dict(patch)))
        snapshot = ref.get()
        return self._prepare_read(dict(snapshot.to_dict() or {}))

    def delete_device(self, device_id: str) -> bool:
        ref = self._device_ref(device_id)
        if not ref.get().exists:
            return False
        # Firestore has no cascading delete: strip subcollections first.
        for name in (TELEMETRY_COLLECTION, LOGS_COLLECTION):
            for batch in self._batched_delete(ref.collection(name).stream()):
                batch.commit()
        ref.delete()
        return True

    def record_revocation(self, device_id: str, reason: str, revoked_at: datetime) -> None:
        self._client.collection(REVOKED_COLLECTION).document(device_id).set(
            {"reason": reason, "revokedAt": revoked_at, "deviceId": device_id}
        )

    def is_revoked(self, device_id: str) -> bool:
        return self._client.collection(REVOKED_COLLECTION).document(device_id).get().exists

    def clear_revocation(self, device_id: str) -> None:
        self._client.collection(REVOKED_COLLECTION).document(device_id).delete()

    # -- telemetry --------------------------------------------------------
    def append_telemetry(self, device_id: str, document: dict[str, Any]) -> str:
        prepared = self._prepare_write(dict(document))
        ref = self._device_ref(device_id).collection(TELEMETRY_COLLECTION).document()
        ref.set(prepared)
        return ref.id

    def list_telemetry(
        self, device_id: str, start: datetime, end: datetime, limit: int
    ) -> list[dict[str, Any]]:
        from google.cloud.firestore import FieldFilter

        query = (
            self._device_ref(device_id)
            .collection(TELEMETRY_COLLECTION)
            .where(filter=FieldFilter("timestamp", ">=", start))
            .where(filter=FieldFilter("timestamp", "<=", end))
            .order_by("timestamp")
            .limit(limit * 4)
        )
        rows = [self._prepare_read(dict(doc.to_dict() or {})) for doc in query.stream()]
        if len(rows) <= limit:
            return rows
        # Uniform down-sampling keeps the chart shape without a second query.
        step = len(rows) / limit
        return [rows[int(index * step)] for index in range(limit)]

    def latest_telemetry(self, device_id: str) -> Optional[dict[str, Any]]:
        query = (
            self._device_ref(device_id)
            .collection(TELEMETRY_COLLECTION)
            .order_by("timestamp", direction="DESCENDING")
            .limit(1)
        )
        for doc in query.stream():
            return self._prepare_read(dict(doc.to_dict() or {}))
        return None

    def latest_telemetry_batch(
        self, device_ids: list[str], max_docs: int = 300
    ) -> dict[str, dict[str, Any]]:
        """One query for the whole dashboard instead of one query per device."""
        wanted = set(device_ids)
        if not wanted:
            return {}
        query = (
            self._client.collection_group(TELEMETRY_COLLECTION)
            .order_by("timestamp", direction="DESCENDING")
            .limit(max_docs)
        )
        latest: dict[str, dict[str, Any]] = {}
        for doc in query.stream():
            data = self._prepare_read(dict(doc.to_dict() or {}))
            owner = data.get("deviceId")
            if owner in wanted and owner not in latest:
                latest[owner] = data
        return latest

    def count_telemetry(self, device_id: Optional[str] = None) -> int:
        if device_id is None:
            aggregation = self._client.collection_group(TELEMETRY_COLLECTION).count()
            return aggregation.get().aggregate_count
        return (
            self._device_ref(device_id)
            .collection(TELEMETRY_COLLECTION)
            .count()
            .get()
            .aggregate_count
        )

    def _batched_delete(self, documents: Iterable[Any]) -> Iterable[Any]:  # type: ignore[type-arg]
        """Group document references into commits of ``batch_size`` items."""
        batch_size = self._settings.cleanup_batch_size
        batch = self._client.batch()
        pending = 0
        for doc in documents:
            batch.delete(doc.reference)
            pending += 1
            if pending >= batch_size:
                yield batch
                batch = self._client.batch()
                pending = 0
        if pending:
            yield batch

    def delete_expired_telemetry(
        self,
        now: datetime,
        batch_size: int = 400,
        page_size: int = 200,
        max_pages: int = 50,
    ) -> dict[str, int]:
        from google.cloud.firestore import FieldFilter

        deleted = 0
        scanned = 0
        pages = 0
        batches = 0
        cursor: Any = None
        while pages < max_pages:
            query = (
                self._client.collection_group(TELEMETRY_COLLECTION)
                .where(filter=FieldFilter(TTL_FIELD, "<=", now))
                .order_by(TTL_FIELD)
                .limit(page_size)
            )
            if cursor is not None:
                query = query.start_after(cursor)
            snapshots = list(query.stream())
            if not snapshots:
                break
            if len(snapshots) < page_size:
                # Last page: delete and stop instead of issuing another query.
                pages += 1
                scanned += len(snapshots)
                for index in range(0, len(snapshots), max(1, batch_size)):
                    chunk = [snapshot.reference for snapshot in snapshots[index : index + max(1, batch_size)]]
                    writer = self._client.bulk_writer()
                    for ref in chunk:
                        writer.delete(ref)
                    writer.close()
                    batches += 1
                    deleted += len(chunk)
                break
            pages += 1
            scanned += len(snapshots)
            cursor = snapshots[-1]
            refs = [snapshot.reference for snapshot in snapshots]
            for index in range(0, len(refs), max(1, batch_size)):
                chunk = refs[index : index + max(1, batch_size)]
                writer = self._client.bulk_writer()
                for ref in chunk:
                    writer.delete(ref)
                writer.close()
                batches += 1
                deleted += len(chunk)
        return {"deleted": deleted, "scanned": scanned, "pages": pages, "batches": batches}

    # -- logs -------------------------------------------------------------
    def append_log(
        self,
        device_id: str,
        event: str,
        level: str = "info",
        message: str = "",
        data: Optional[dict[str, Any]] = None,
    ) -> str:
        from app.utils.time import utcnow

        ref = self._device_ref(device_id).collection(LOGS_COLLECTION).document()
        ref.set(
            {
                "logId": ref.id,
                "deviceId": device_id,
                "event": event,
                "level": level,
                "message": message,
                "data": data or {},
                "timestamp": utcnow(),
            }
        )
        return ref.id

    def list_logs(self, device_id: Optional[str], limit: int = 100) -> list[dict[str, Any]]:
        if device_id:
            collection = self._device_ref(device_id).collection(LOGS_COLLECTION)
        else:
            collection = self._client.collection_group(LOGS_COLLECTION)
        query = collection.order_by("timestamp", direction="DESCENDING").limit(limit)
        return [self._prepare_read(dict(doc.to_dict() or {})) for doc in query.stream()]

    # -- retention --------------------------------------------------------
    def ensure_ttl_policy(self, ttl_field: str = TTL_FIELD) -> dict[str, Any]:
        """Register a Firestore TTL policy on ``ttl_field``.

        Uses the Firestore REST API (``fields`` resource) because the Python
        client library does not expose TTL management.  Failures are reported
        instead of raised: the scheduled cleanup job remains the safety net.
        """
        if not self._settings.enable_ttl_policy:
            return {"supported": True, "status": "disabled", "field": ttl_field}
        try:
            import httpx

            token = self._access_token()
            project = self._settings.firebase_project_id
            url = (
                "https://firestore.googleapis.com/v1/projects/"
                f"{project}/databases/{self._database_id}/fields/{ttl_field}"
            )
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"ttlConfig": {"state": "CREATED"}},
                timeout=15.0,
            )
            if response.status_code in (200, 201):
                return {"supported": True, "status": "enabled", "field": ttl_field}
            return {
                "supported": True,
                "status": "error",
                "field": ttl_field,
                "detail": f"HTTP {response.status_code}",
            }
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning(
                "ttl_policy_failed", "could not enable Firestore TTL", error=str(exc)
            )
            return {"supported": True, "status": "unavailable", "field": ttl_field, "detail": str(exc)}

    def _access_token(self) -> str:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        key = self._settings.private_key()
        if key and self._settings.firebase_client_email:
            credentials = service_account.Credentials.from_service_account_info(
                {
                    "type": "service_account",
                    "project_id": self._settings.firebase_project_id,
                    "private_key_id": "",
                    "private_key": key,
                    "client_email": self._settings.firebase_client_email,
                    "token_uri": "https://oauth2.googleapis.com/token",
                },
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        else:
            import google.auth

            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        credentials.refresh(Request())
        return credentials.token


# ---------------------------------------------------------------------------
# Global store accessor
# ---------------------------------------------------------------------------

_store: Optional[BaseStore] = None
_store_lock = threading.Lock()


def get_store(settings: Optional[Settings] = None) -> BaseStore:
    """Return the process-wide store, initialising it on first use."""
    global _store
    settings = settings or get_settings()
    with _store_lock:
        if _store is None:
            if settings.firestore_enabled:
                logger.info("store_initialised", "using Firestore", project=settings.firebase_project_id)
                _store = FirestoreStore(settings)
            else:
                logger.warning(
                    "store_initialised",
                    "Firestore is not configured - using the in-memory store. "
                    "Data is lost on restart and is NOT suitable for production.",
                )
                _store = InMemoryStore()
        return _store


def set_store(store: Optional[BaseStore]) -> None:
    """Inject a store (tests / advanced deployments)."""
    global _store
    with _store_lock:
        _store = store


def reset_store() -> None:
    set_store(None)
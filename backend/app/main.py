"""PC Monitor backend - FastAPI application entrypoint.

Architecture:  Next.js (browser)  ->  FastAPI (this service)  ->  Firestore

The browser never touches Firestore or Firebase Admin credentials, and the
Windows agent only ever talks to this API with its own per-device token.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import devices as devices_api
from app.api import heartbeat as heartbeat_api
from app.api import logs as logs_api
from app.api import telemetry as telemetry_api
from app.core.config import Settings, get_settings
from app.core.firebase import get_store
from app.core.middleware import install_middleware
from app.models.common import ApiMetaResponse, HealthResponse
from app.services.cleanup_service import (
    get_cleanup_service,
    start_scheduler,
    stop_scheduler,
)
from app.utils.logging import configure_logging, get_logger
from app.utils.time import utcnow

logger = get_logger("pc-monitor")

START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.app_name)
    store = get_store(settings)
    cleanup = get_cleanup_service()
    logger.info(
        "startup",
        "PC Monitor API starting",
        version=settings.version,
        environment=settings.environment,
        database="firestore" if settings.firestore_enabled else "in-memory",
    )
    cleanup.setup_ttl()
    start_scheduler(cleanup, settings.cleanup_interval_minutes)
    try:
        yield
    finally:
        await stop_scheduler()
        logger.info("shutdown", "PC Monitor API stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory (used by tests and by uvicorn)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.app_name)

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=(
            "Telemetry API for PC Monitor.\n\n"
            "* Agents register, send heartbeats and telemetry samples.\n"
            "* The dashboard reads devices, history and logs.\n"
            "* Monitoring only - this API deliberately exposes **no** remote "
            "control, screen capture or command execution surface."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Device-Token",
            "X-Cleanup-Token",
        ],
        max_age=600,
    )
    install_middleware(app, settings)

    app.include_router(devices_api.router)
    app.include_router(heartbeat_api.router)
    app.include_router(logs_api.router)
    app.include_router(telemetry_api.router)

    _register_error_handlers(app)
    _register_meta_routes(app, settings)
    return app


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = getattr(exc, "code", None) or _code_for_status(exc.status_code)
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": detail}},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error.get("loc", [])[1:]) or "body",
                "message": error.get("msg", "invalid value"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()[:10]
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "request payload failed validation",
                    "details": details,
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_error",
            "unhandled exception",
            path=request.url.path,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "unexpected server error",
                }
            },
        )


def _code_for_status(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "authentication_required",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
        422: "validation_error",
        429: "rate_limited",
    }.get(status_code, "error")


# ---------------------------------------------------------------------------
# Meta endpoints
# ---------------------------------------------------------------------------
def _register_meta_routes(app: FastAPI, settings: Settings) -> None:
    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return {
            "name": settings.app_name,
            "version": settings.version,
            "docs": "/docs",
            "redoc": "/redoc",
            "health": "/health",
        }

    @app.get("/health", response_model=HealthResponse, tags=["system"], summary="Health check")
    async def health() -> HealthResponse:
        settings_local = get_settings()
        return HealthResponse(
            status="ok",
            version=settings_local.version,
            environment=settings_local.environment,
            database="firestore" if settings_local.firestore_enabled else "in-memory",
            time=utcnow(),
            uptimeSeconds=round(time.time() - START_TIME, 3),
            retentionDays=settings_local.telemetry_retention_days,
            onlineThresholdSeconds=settings_local.online_threshold_seconds,
        )

    @app.get("/api/meta", response_model=ApiMetaResponse, tags=["system"], summary="Client configuration")
    async def meta() -> ApiMetaResponse:
        current = get_settings()
        return ApiMetaResponse(
            name=current.app_name,
            version=current.version,
            environment=current.environment,
            retentionDays=current.telemetry_retention_days,
            supportedRanges=current.supported_ranges(),
            telemetryIntervalSeconds=current.default_telemetry_interval_seconds,
            heartbeatIntervalSeconds=60,
            onlineThresholdSeconds=current.online_threshold_seconds,
            maxTelemetryPoints=current.max_telemetry_points,
        )


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - required for container/cloud hosting
        port=8000,
        reload=get_settings().debug,
    )
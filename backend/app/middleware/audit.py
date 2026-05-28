"""Request audit middleware — logs every request with timing and request-id."""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

import structlog

_logger = structlog.get_logger("centras.http")

_SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers["X-Request-ID"] = request_id

        ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
        # Use only first IP if X-Forwarded-For has chain
        ip = ip.split(",")[0].strip()

        _logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
            ip=ip,
            user_agent=request.headers.get("User-Agent", ""),
        )

        return response

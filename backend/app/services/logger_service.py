"""
Structured logging service.

Configures structlog with JSON rendering for production and console rendering
for development. Persists important events to the AuditLog table so the
frontend can display a live log stream without requiring file-system access.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import structlog
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

# Module-level logger — used by all services via `from app.services.logger_service import logger`.
logger: structlog.BoundLogger = structlog.get_logger("centras")


def configure_logging() -> None:
    """
    Configure structlog processors and stdlib logging integration.
    Called once at application startup from main.py.
    """
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.environment == "development":
        renderer: Any = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Suppress noisy third-party loggers in production.
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "yfinance"):
        lvl = logging.WARNING if settings.environment != "development" else log_level
        logging.getLogger(noisy).setLevel(lvl)


async def log_event(
    db: AsyncSession,
    level: str,
    event: str,
    message: str,
    context: Optional[dict[str, Any]] = None,
    request_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """
    Write a structured event to both structlog and the AuditLog DB table.

    Failures to write to the DB are logged but do not propagate — audit logging
    must never break application flow.

    Args:
        db:         Async DB session (injected via dependency).
        level:      Log level string: INFO, WARNING, ERROR, DEBUG.
        event:      Machine-readable event identifier, e.g. "analysis.run".
        message:    Human-readable description.
        context:    Arbitrary JSON-serializable dict for extra context.
        request_id: UUID from X-Request-ID header for correlation.
        ip:         Client IP address.
        user_agent: Client User-Agent string.
    """
    from app.models.audit_log import AuditLog  # local import avoids circular dep at module load

    # Emit to structlog immediately (synchronous — no DB call needed for log output).
    bound = logger.bind(
        event=event,
        request_id=request_id,
        ip=ip,
    )
    log_fn = getattr(bound, level.lower(), bound.info)
    log_fn(message, **(context or {}))

    # Persist to DB for the /api/logs endpoints.
    try:
        entry = AuditLog(
            level=level.upper()[:10],
            event=event[:100],
            message=message,
            context=context,
            request_id=request_id,
            ip_address=ip[:45] if ip else None,
            user_agent=user_agent[:512] if user_agent else None,
        )
        db.add(entry)
        await db.flush()  # write within the caller's transaction; caller commits
    except Exception as exc:
        # Do not re-raise — audit failure must not abort the parent operation.
        logging.getLogger("centras.logger_service").error(
            "Failed to persist audit log entry: %s", exc, exc_info=True
        )


async def get_recent_logs(
    db: AsyncSession,
    limit: int = 50,
    level_filter: str = "ALL",
) -> list[Any]:
    """
    Retrieve the most recent AuditLog entries ordered by timestamp descending.

    Args:
        db:           Async DB session.
        limit:        Maximum number of rows to return.
        level_filter: When not "ALL", only return entries whose level matches
                      this value (case-insensitive).  Accepted values are the
                      standard log levels: DEBUG, INFO, WARNING, ERROR, or the
                      sentinel "ALL" to return every level.

    Returns:
        List of AuditLog ORM instances.
    """
    from app.models.audit_log import AuditLog

    limit = max(1, min(limit, 500))  # guard against absurd limit values
    stmt = select(AuditLog).order_by(desc(AuditLog.timestamp)).limit(limit)

    if level_filter and level_filter.upper() != "ALL":
        stmt = stmt.where(AuditLog.level == level_filter.upper())

    result = await db.execute(stmt)
    return list(result.scalars().all())

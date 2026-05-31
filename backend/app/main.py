"""FastAPI application entrypoint for Centras Tokenizer."""
from __future__ import annotations

import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import init_db
from app.middleware.audit import AuditMiddleware
from app.middleware.rate_limiter import setup_rate_limiter
from app.routers import analysis, auth, health, logs, market, news

logger = structlog.get_logger("centras.main")

settings = get_settings()


def _safe_database_url_for_log(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return parsed.scheme or "local"
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"***@{hostname}{port}", parsed.path, "", ""))

app = FastAPI(
    title="Centras Tokenizer API",
    description=(
        "Financial intelligence platform — OHLCV tokenization + Gemini AI analysis. "
        "Inspired by Kronos (NeurIPS 2024) hierarchical discretization concept."
    ),
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# -------------------------------------------------------------------
# CORS
# -------------------------------------------------------------------
cors_origins = settings.cors_origins
if settings.environment == "development":
    # In dev, allow all origins for easy local testing
    cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],  # credentials not allowed with wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Rate limiting
# -------------------------------------------------------------------
setup_rate_limiter(app)

# -------------------------------------------------------------------
# Request audit logging
# -------------------------------------------------------------------
app.add_middleware(AuditMiddleware)

# -------------------------------------------------------------------
# Routers
# -------------------------------------------------------------------
app.include_router(health.router)                    # GET /health
app.include_router(auth.router, prefix="/api")       # POST /api/auth/login
app.include_router(market.router, prefix="/api")     # GET /api/market/...
app.include_router(analysis.router, prefix="/api")   # POST /api/analysis/...
app.include_router(news.router, prefix="/api")       # GET /api/news/...
app.include_router(logs.router, prefix="/api")       # GET /api/logs/...


# -------------------------------------------------------------------
# Lifecycle
# -------------------------------------------------------------------
@app.on_event("startup")
async def startup() -> None:
    # Run Alembic migrations before accepting any requests.
    # This is idempotent: if the DB is already up-to-date, it exits instantly.
    # Keeps Railway deployments self-migrating without a separate release phase.
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            logger.info("alembic_migrations_applied", output=result.stdout.strip() or "already up to date")
        else:
            stderr = result.stderr
            # If the database was created by SQLAlchemy create_all before Alembic was introduced,
            # applying 001_initial will fail because 'tickers' already exists.
            if "DuplicateTableError" in stderr and "tickers" in stderr:
                logger.info("alembic_stamping_existing_db", message="Found existing tables. Stamping 001_initial...")
                subprocess.run([sys.executable, "-m", "alembic", "stamp", "001_initial"], check=True)
                
                # Retry upgrade to apply any pending migrations (e.g. 002_forecast_fields)
                result2 = subprocess.run(
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result2.returncode == 0:
                    logger.info("alembic_migrations_applied_after_stamp", output=result2.stdout.strip() or "already up to date")
                else:
                    logger.error("alembic_migration_failed_after_stamp", stderr=result2.stderr.strip())
            else:
                logger.error("alembic_migration_failed", stderr=stderr.strip())
    except Exception as exc:
        logger.error("alembic_migration_error", error=str(exc))

    # Fallback: create any tables not yet managed by Alembic (dev / SQLite)
    await init_db()
    logger.info(
        "centras_startup",
        environment=settings.environment,
        gemini_configured=bool(settings.gemini_api_key),
        database_url=_safe_database_url_for_log(settings.database_url),
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    logger.info("centras_shutdown")


# -------------------------------------------------------------------
# Global exception handlers
# -------------------------------------------------------------------
@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check logs for details."},
    )

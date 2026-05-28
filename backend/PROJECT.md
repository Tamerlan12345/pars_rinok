# Centras Tokenizer — Project Documentation

## Architecture

**Stack:** Python 3.11+, FastAPI 0.111, SQLAlchemy 2 (async), asyncpg, PostgreSQL  
**Runtime targets:** Railway (backend + PostgreSQL), any CORS-enabled frontend  
**AI:** Google Gemini 1.5 Flash via google-genai SDK  
**Data:** yfinance (OHLCV), Yahoo Finance RSS (news), feedparser  

```
Request → AuditMiddleware → RateLimiter → Router
                                            │
                          ┌─────────────────┼─────────────────────────┐
                          │                 │                           │
                     /health          /api/auth         /api/market, /api/analysis,
                                                        /api/news, /api/logs
                                            │
                                    Services layer
                                    ├── tokenizer.py     (pure NumPy)
                                    ├── gemini_client.py (threadpool + tenacity)
                                    ├── data_fetcher.py  (asyncio.to_thread)
                                    └── logger_service.py (structlog + DB)
                                            │
                                    SQLAlchemy AsyncSession
                                            │
                                    PostgreSQL (Railway)
```

## Module Registry

| Module | Path | Responsibility | Depends on | Depended on by |
|--------|------|----------------|------------|----------------|
| config | app/config.py | Settings singleton via pydantic-settings | pydantic-settings, env | all |
| database | app/database.py | Engine, session factory, Base, get_db | config, sqlalchemy | all routers/services |
| models | app/models/ | ORM table definitions | database.Base | routers, alembic |
| schemas | app/schemas/ | Pydantic v2 request/response contracts | pydantic | routers |
| tokenizer | app/services/tokenizer.py | OHLCV → hierarchical discrete tokens | numpy | analysis router |
| gemini_client | app/services/gemini_client.py | Gemini API call, retry, mock fallback | google-genai, tenacity, config | analysis router |
| data_fetcher | app/services/data_fetcher.py | yfinance OHLCV + Yahoo RSS news | yfinance, feedparser | market/analysis/news routers |
| logger_service | app/services/logger_service.py | structlog config + AuditLog persistence | structlog, sqlalchemy | routers, middleware |
| rate_limiter | app/middleware/rate_limiter.py | slowapi limiter setup | slowapi | main.py |
| audit | app/middleware/audit.py | Per-request timing, X-Request-ID | starlette | main.py |
| health router | app/routers/health.py | GET /health | database | main.py |
| auth router | app/routers/auth.py | POST /api/auth/login, get_current_user dep | jose, passlib, config | analysis/logs routers |
| market router | app/routers/market.py | OHLCV fetch, ticker CRUD, candle query | data_fetcher, models | analysis router |
| analysis router | app/routers/analysis.py | Full pipeline: candles→tokens→Gemini→save | tokenizer, gemini_client, data_fetcher | — |
| news router | app/routers/news.py | Yahoo RSS fetch, upsert, query | data_fetcher, models | — |
| logs router | app/routers/logs.py | AuditLog query + SSE stream | logger_service | — |
| main | app/main.py | App factory, middleware, router assembly | all above | uvicorn |

## Decisions Log

| # | Date | Decision | Context | Alternatives rejected | Reversal cost |
|---|------|----------|---------|----------------------|---------------|
| 1 | 2026-05-28 | Denormalize ticker_symbol on Candle table | Avoid JOIN on every candle read — hot path | FK-only join on ticker_id: adds JOIN latency at scale | Low — add FK join query when needed |
| 2 | 2026-05-28 | google-genai sync SDK in threadpool | google-genai 1.0 has no native async; blocking event loop is worse | httpx raw REST call: no type safety, manual auth | Medium — switch when SDK gains async |
| 3 | 2026-05-28 | Plain-text admin password accepted from env var | Single-admin setup; password lives in Railway env var, never in code or DB | Force bcrypt hash in env: raises UX friction for initial deploy | Low — validator already checks for bcrypt prefix |
| 4 | 2026-05-28 | 1-hour cache TTL on candles by latest candle timestamp | Prevents hammering yfinance on every frontend refresh | Per-row insertion timestamp: requires schema change | Low |
| 5 | 2026-05-28 | SSE /api/logs/stream polls DB every 3s | Simple, no extra infra (Redis pub/sub, WebSocket server) needed | WebSocket: needs token-in-query workaround for browser EventSource | Medium — switch to Redis pub/sub if log volume grows |
| 6 | 2026-05-28 | init_db() on startup creates tables if missing | Removes cold-start dependency on manual migration | Alembic-only: requires migration run before first start on Railway | Low — alembic is still available for schema changes |
| 7 | 2026-05-28 | Add `aiosqlite` and SQLite default local DB URL | Enables local execution out of the box without running Postgres | Force Postgres locally (requires manual setup) | Low |
| 8 | 2026-05-28 | Set custom requests Session with User-Agent in yfinance | Yahoo Finance blocks default python scraper agents | Use paid API (costs money) | Low |

## Task Log

| # | Task | Mode | Status | Files | Goals satisfied | Notes |
|---|------|------|--------|-------|----------------|-------|
| 1 | Write all backend files for Centras Tokenizer | Feature | Complete | All files under backend/ | G1–G4 | Initial full implementation with SQLite fallback and yfinance fix |

## Known Issues & Technical Debt

| Issue | Severity | Location | Impact | Owner | Plan |
|-------|----------|----------|--------|-------|------|
| google-genai SDK is synchronous | Low | gemini_client.py | Blocks one thread per Gemini call | — | Switch to async when SDK supports it |
| SSE /logs/stream has no auth | Low | routers/logs.py | Read-only log data exposed without token | — | Protect at Railway ingress or add token-in-query |
| yfinance MultiIndex handling | Low | data_fetcher.py | May need adjustment on yfinance API changes | — | Pin yfinance version, monitor changelog |

## Build & Test Commands

```bash
# Install
pip install -r requirements.txt

# Dev server (local)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run migrations
alembic upgrade head

# Generate new migration
alembic revision --autogenerate -m "description"

# Downgrade one step
alembic downgrade -1
```

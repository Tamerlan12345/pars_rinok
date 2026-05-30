# PROJECT.md — Centras Tokenizer

## Architecture

**Stack:** FastAPI (Python 3.11) + React 18 (Vite) + PostgreSQL 15  
**Runtime targets:** Railway cloud (backend + PostgreSQL + frontend as separate services)  
**AI:** Google Gemini 1.5 Flash via `google-genai` SDK  
**Data:** yfinance (OHLCV) + Yahoo Finance RSS (news)  
**Auth:** JWT HS256, single admin user (configured via env)  
**Layer map:** Browser → Vite SPA → FastAPI → asyncpg → PostgreSQL

## Module Registry

| Module | Path | Responsibility | Depends on | Depended on by |
|--------|------|---------------|------------|----------------|
| config | backend/app/config.py | Settings from env | pydantic-settings | All modules |
| database | backend/app/database.py | Async SQLAlchemy engine, session factory | config, sqlalchemy | All routers |
| tokenizer | backend/app/services/tokenizer.py | OHLCV → coarse/fine tokens | numpy | analysis router |
| gemini_client | backend/app/services/gemini_client.py | Gemini API calls | google-genai, tenacity | analysis router |
| data_fetcher | backend/app/services/data_fetcher.py | yfinance + Yahoo RSS | yfinance, feedparser | market/news routers |
| logger_service | backend/app/services/logger_service.py | structlog → AuditLog table | structlog, database | All routers, middleware |
| rate_limiter | backend/app/middleware/rate_limiter.py | slowapi rate limiting | slowapi | main.py |
| audit | backend/app/middleware/audit.py | Request logging middleware | logger_service | main.py |

## Decisions Log

| # | Date | Decision | Context | Alternatives rejected | Reversal cost |
|---|------|---------|---------|----------------------|---------------|
| 1 | 2026-05-28 | Use `google-genai` SDK (not `google-generativeai`) | google-genai is current recommended client | google-generativeai (deprecated) | Low — same API surface |
| 2 | 2026-05-28 | Gemini 1.5 Flash as AI model | Free tier, fast, sufficient context window | Gemini Pro (paid, slower), GPT-4 (not Gemini) | Low |
| 3 | 2026-05-28 | Single admin user via env vars | Internal tool, no user management needed | Full user table with registration | Medium — requires user table migration |
| 4 | 2026-05-28 | yfinance + Yahoo RSS (not paid API) | Cost-free for internal use | Alpha Vantage, Polygon.io (paid) | Low — service interface abstracted |
| 5 | 2026-05-28 | pool_size=5, max_overflow=10 | 4 GB RAM constraint | Higher pool (more memory) | Low |
| 6 | 2026-05-28 | Tokenization: own log-return quantization | No Kronos code reuse; MIT license doesn't require, but we write original impl | Direct BSQ copy | None — already done |
| 7 | 2026-05-28 | SSE for log streaming (not WebSocket) | Simpler, unidirectional, no WS lib needed | WebSocket (overkill for logs) | Medium |
| 8 | 2026-05-28 | Railway deployment (monorepo, 2 services) | User constraint — Railway for PostgreSQL and app | Render, Fly.io | Low |
| 9 | 2026-05-28 | Replace `postgresql://` → `postgresql+asyncpg://` in DATABASE_URL | asyncpg driver requirement with SQLAlchemy async | psycopg2 (sync, would block) | Low |
| 10 | 2026-05-28 | Pure JS (no TypeScript) for frontend | User constraint; avoids build complexity | TypeScript (better DX but extra tooling) | Medium — TS migration needs type declarations |
| 11 | 2026-05-28 | Add `aiosqlite` and SQLite default local DB URL | Enables local execution out of the box without running Postgres | Force Postgres locally (requires manual setup) | Low |
| 12 | 2026-05-28 | Set custom requests Session with User-Agent in yfinance | Yahoo Finance blocks default python scraper agents | Use paid API (costs money) | Low |
| 13 | 2026-05-30 | Fallback to Yahoo Chart API + Cookie Session | yfinance blocked heavily on Railway/AWS ASNs, Stooq requires API keys now | Stooq (broken), Alpha Vantage (requires key) | Low |

## Task Log

| # | Task | Mode | Status | Files | Goals satisfied | Notes |
|---|------|------|--------|-------|----------------|-------|
| 1 | Initial Centras Tokenizer backend build | Feature | Complete | backend/** | G1-G4 | Full-stack from scratch with SQLite fallback and yfinance fix |
| 2 | Frontend: React 18 + Vite SPA | Feature | Complete | frontend/** | G1-G4 | 14 files; glassmorphism dark theme; Railway-ready |
| 3 | Fix OHLCV fetch via Yahoo Chart API & Frontend chart rendering | Fix | Complete | backend/app/services/data_fetcher.py, frontend/src/components/CandleChart.jsx | G1-G4 | Bypassed Yahoo blocks, fixed `asyncpg` offset DataError, fixed `lightweight-charts` rendering |

## Known Issues & Technical Debt

| Issue | Severity | Location | Impact | Owner | Plan |
|-------|---------|---------|--------|-------|------|
| yfinance unofficial | Medium | data_fetcher.py | Data may break if Yahoo changes endpoints | - | Monitor; add fallback to mock data |
| Single admin user | Low | auth.py | No multi-user support | - | Add users table if needed |
| No Redis cache | Low | market router | Cache is in-memory dict, lost on restart | - | Add Redis on Railway if needed |
| Alembic autogenerate | Low | alembic/ | Manual migration written, autogenerate not configured | - | Configure autogenerate for future migrations |

## Build & Test Commands

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev        # dev server
npm run build      # production build

# Health check
curl http://localhost:8000/health
```

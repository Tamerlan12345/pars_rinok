# Centras Tokenizer

**Financial Intelligence Platform** — AI-powered OHLCV analysis with Gemini integration.

## Architecture

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI 0.111 + asyncpg + SQLAlchemy 2 |
| AI Engine | Google Gemini 1.5 Flash |
| Database | PostgreSQL 15 (Railway) |
| Data Feed | yfinance + Yahoo Finance RSS |
| Frontend | React 18 + Vite 5 + Vanilla CSS |
| Auth | JWT (HS256) |
| Rate Limiting | slowapi |
| Logging | structlog → PostgreSQL |

## Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- Node.js 20+
- PostgreSQL 15 (or Railway PostgreSQL)

### Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # Fill in your values
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env            # Set VITE_API_URL
npm run dev
```

Open http://localhost:5173

## Railway Deployment

### Backend Service
1. Create a new service from this repo, root directory: `backend/`
2. Set environment variables (see `backend/.env.example`)
3. Railway auto-detects Python via Nixpacks

### Frontend Service
1. Create a new service from this repo, root directory: `frontend/`
2. Set `VITE_API_URL` to your backend Railway URL
3. Railway runs `npm install && npm run build && npx serve -s dist`

### PostgreSQL
1. Add PostgreSQL plugin in Railway
2. Copy `DATABASE_URL` to backend service variables
   - Replace `postgresql://` with `postgresql+asyncpg://`

## Environment Variables

### Backend (`.env`)
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` Railway PostgreSQL URL |
| `GEMINI_API_KEY` | Google AI Studio API key |
| `JWT_SECRET_KEY` | Long random secret (32+ chars) |
| `ADMIN_USERNAME` | Login username |
| `ADMIN_PASSWORD` | Login password |
| `CORS_ORIGINS_RAW` | Frontend URL (Railway URL) |

### Frontend (`.env`)
| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | Backend Railway URL |

## Credits

Conceptually inspired by Kronos (shiyu-coder/Kronos, NeurIPS 2024) — a foundation model
for the language of financial markets. No Kronos source code is used. Tokenization
logic is an independent implementation of the coarse/fine hierarchical discretization
concept applied to OHLCV log-returns.

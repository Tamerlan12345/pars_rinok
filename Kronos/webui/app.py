"""
Kronos Financial Forecasting — Flask WebUI Backend
===================================================
Serves the K-line (candlestick) forecasting interface.

Features:
- JWT authentication (flask-jwt-extended) with in-memory user store
- Werkzeug password hashing
- Public  GET  /api/health
- Protected routes: /api/predict, /api/load-model, /api/load-data, /api/data-files
- Auth routes: POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me
- python-dotenv for SECRET_KEY / ADMIN_PASSWORD env loading
- Plotly-based candlestick charting helpers
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------------------
# Environment / configuration
# ---------------------------------------------------------------------------
load_dotenv()  # loads .env from CWD or parent directories

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("kronos.webui")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"change-me-in-production", "admin123"} or normalized.startswith("replace_")


_SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
_ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")
_GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
_FLASK_ENV: str = os.getenv("FLASK_ENV", "development").lower()
_IS_PRODUCTION: bool = _FLASK_ENV == "production"
_CORS_ORIGINS_RAW: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
_KRONOS_REPO_PATH: str = os.getenv("KRONOS_REPO_PATH") or str(Path(__file__).resolve().parents[1])
_KRONOS_MODEL_ID: str = os.getenv("KRONOS_MODEL_ID", "NeoQuasar/Kronos-base")
_KRONOS_TOKENIZER_ID: str = os.getenv("KRONOS_TOKENIZER_ID", "NeoQuasar/Kronos-Tokenizer-base")
_KRONOS_MAX_CONTEXT: int = _env_int("KRONOS_MAX_CONTEXT", 512)
_ALLOW_KRONOS_STUB: bool = _env_bool("ALLOW_KRONOS_STUB")

if _SECRET_KEY == "change-me-in-production":
    logger.warning(
        "SECRET_KEY is set to the default placeholder — "
        "set a strong random value via the SECRET_KEY env variable before deploying."
    )

if _IS_PRODUCTION:
    if _is_placeholder(_SECRET_KEY) or len(_SECRET_KEY) < 32:
        raise RuntimeError("SECRET_KEY must be a strong 32+ character value in production")
    if _is_placeholder(_ADMIN_PASSWORD) or len(_ADMIN_PASSWORD) < 12:
        raise RuntimeError("ADMIN_PASSWORD must be changed to a strong 12+ character value in production")
    if _CORS_ORIGINS_RAW.strip() == "*":
        raise RuntimeError("CORS_ORIGINS cannot be '*' in production")

# ---------------------------------------------------------------------------
# In-memory user store  (username → {"password_hash": ..., "role": ...})
# ---------------------------------------------------------------------------
_USERS: dict[str, dict[str, str]] = {
    "admin": {
        "password_hash": generate_password_hash(_ADMIN_PASSWORD),
        "role": "admin",
    }
}

# Simple token blocklist for logout (stores JTI strings).
# A production system would use Redis or a DB table.
_REVOKED_TOKENS: set[str] = set()

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    app = Flask(__name__)

    # --- Core config -------------------------------------------------------
    app.config["SECRET_KEY"] = _SECRET_KEY
    app.config["JWT_SECRET_KEY"] = _SECRET_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=8)
    app.config["JWT_BLACKLIST_ENABLED"] = True
    app.config["JWT_BLACKLIST_TOKEN_CHECKS"] = ["access"]
    app.config["JSON_SORT_KEYS"] = False

    # --- Extensions --------------------------------------------------------
    cors_origins: str | list[str]
    if _CORS_ORIGINS_RAW.strip() == "*":
        cors_origins = "*"
    else:
        cors_origins = [o.strip() for o in _CORS_ORIGINS_RAW.split(",") if o.strip()]
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})

    jwt = JWTManager(app)

    # Token revocation check
    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header: dict, jwt_payload: dict) -> bool:  # noqa: ARG001
        return jwt_payload.get("jti", "") in _REVOKED_TOKENS

    # Custom error responses
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header: dict, jwt_payload: dict) -> tuple:  # noqa: ARG001
        return jsonify({"error": "Token has expired", "code": "TOKEN_EXPIRED"}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(reason: str) -> tuple:
        return jsonify({"error": f"Invalid token: {reason}", "code": "TOKEN_INVALID"}), 422

    @jwt.unauthorized_loader
    def missing_token_callback(reason: str) -> tuple:
        return jsonify({"error": f"Authorisation required: {reason}", "code": "TOKEN_MISSING"}), 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header: dict, jwt_payload: dict) -> tuple:  # noqa: ARG001
        return jsonify({"error": "Token has been revoked", "code": "TOKEN_REVOKED"}), 401

    # --- Register blueprints / routes -------------------------------------
    _register_routes(app)

    # --- Register optional analysis blueprint (requires analysis_routes.py) ---
    # analysis_routes.py imports from `webui.gemini` so we do a late import
    # here after the Flask app and JWT extension are already configured.
    try:
        from analysis_routes import analysis_bp  # type: ignore[import]

        app.register_blueprint(analysis_bp)
        logger.info("Registered /api/analyze blueprint from analysis_routes.py")
    except ImportError:
        logger.info(
            "analysis_routes not importable — /api/analyze endpoint disabled. "
            "Run with PYTHONPATH set to the webui directory to enable it."
        )

    return app


# ---------------------------------------------------------------------------
# Model / data state  (module-level singletons, reset-safe)
# ---------------------------------------------------------------------------
_state: dict[str, Any] = {
    "model": None,           # loaded Kronos model object
    "predictor": None,       # loaded KronosPredictor-compatible object
    "model_id": None,        # Hugging Face model id or local model path
    "tokenizer_id": None,    # Hugging Face tokenizer id or local tokenizer path
    "model_path": None,      # backward-compatible alias for older UI/tests
    "data": None,            # pd.DataFrame of current OHLCV data
    "data_path": None,       # str path of the loaded data file
    "prediction_results": [],
    "actual_data": [],
}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int, field: str) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _request_bool(value: Any, *, default: bool, field: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{field} must be a boolean")


def _ensure_kronos_import_path() -> None:
    repo_path = Path(_KRONOS_REPO_PATH).expanduser()
    if (repo_path / "model").is_dir():
        repo_path_str = str(repo_path.resolve())
        if repo_path_str not in sys.path:
            sys.path.insert(0, repo_path_str)

# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def _register_routes(app: Flask) -> None:
    # -----------------------------------------------------------------------
    # Public
    # -----------------------------------------------------------------------

    @app.get("/api/health")
    def health():
        """Public health-check endpoint — no auth required."""
        return jsonify(
            {
                "status": "ok",
                "service": "kronos-webui",
                "version": "1.0.0",
                "model_loaded": _state["predictor"] is not None,
                "data_loaded": _state["data"] is not None,
                "gemini_configured": bool(_GEMINI_API_KEY),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    # -----------------------------------------------------------------------
    # Auth
    # -----------------------------------------------------------------------

    @app.post("/api/auth/login")
    def auth_login():
        """
        Authenticate and return a JWT access token.

        Request body (JSON):
            {"username": "admin", "password": "..."}

        Response:
            {"access_token": "...", "token_type": "bearer", "expires_in": 28800}
        """
        body = request.get_json(silent=True) or {}
        username: str = body.get("username", "").strip()
        password: str = body.get("password", "")

        if not username or not password:
            return jsonify({"error": "username and password are required"}), 400

        user = _USERS.get(username)
        if user is None or not check_password_hash(user["password_hash"], password):
            logger.warning("Failed login attempt for user %r", username)
            return jsonify({"error": "Incorrect username or password"}), 401

        access_token = create_access_token(
            identity=username,
            additional_claims={"role": user["role"]},
        )
        expires_config = app.config["JWT_ACCESS_TOKEN_EXPIRES"]
        expires_in = None if expires_config is False else int(expires_config.total_seconds())
        logger.info("User %r logged in", username)
        return jsonify(
            {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": expires_in,
                "username": username,
                "role": user["role"],
            }
        )

    @app.post("/api/auth/logout")
    @jwt_required()
    def auth_logout():
        """
        Revoke the current JWT (adds JTI to blocklist).
        Requires a valid Bearer token.
        """
        jti: str = get_jwt().get("jti", "")
        if jti:
            _REVOKED_TOKENS.add(jti)
        identity = get_jwt_identity()
        logger.info("User %r logged out (jti=%s)", identity, jti)
        return jsonify({"message": "Successfully logged out"})

    @app.get("/api/auth/me")
    @jwt_required()
    def auth_me():
        """Return the authenticated user's profile."""
        identity: str = get_jwt_identity()
        claims: dict = get_jwt()
        user = _USERS.get(identity, {})
        return jsonify(
            {
                "username": identity,
                "role": claims.get("role", user.get("role", "unknown")),
            }
        )

    # -----------------------------------------------------------------------
    # Data files  (protected)
    # -----------------------------------------------------------------------

    @app.get("/api/data-files")
    @jwt_required()
    def data_files():
        """
        Return a list of available CSV / Parquet data files discovered in
        the ./data directory (relative to this file) and the CWD.
        """
        search_dirs = [
            Path(__file__).parent / "data",
            Path.cwd() / "data",
        ]
        found: list[dict[str, Any]] = []
        seen: set[Path] = set()

        for directory in search_dirs:
            if not directory.is_dir():
                continue
            for ext in ("*.csv", "*.parquet", "*.xlsx"):
                for fp in sorted(directory.glob(ext)):
                    resolved = fp.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    stat = fp.stat()
                    found.append(
                        {
                            "name": fp.name,
                            "path": str(fp.resolve()),
                            "size_bytes": stat.st_size,
                            "modified": datetime.fromtimestamp(
                                stat.st_mtime, tz=timezone.utc
                            ).isoformat(),
                        }
                    )

        return jsonify({"files": found, "count": len(found)})

    @app.get("/api/available-models")
    def available_models():
        return jsonify(
            {
                "models": [
                    {
                        "id": _KRONOS_MODEL_ID,
                        "tokenizer_id": _KRONOS_TOKENIZER_ID,
                        "max_context": _KRONOS_MAX_CONTEXT,
                        "default": True,
                    }
                ]
            }
        )

    # -----------------------------------------------------------------------
    # Load data  (protected)
    # -----------------------------------------------------------------------

    @app.post("/api/load-data")
    @jwt_required()
    def load_data():
        """
        Load an OHLCV CSV / Parquet / Excel file into memory.

        Request body (JSON):
            {"file_path": "/absolute/path/to/data.csv"}
        """
        body = request.get_json(silent=True) or {}
        file_path_str: str = body.get("file_path", "").strip()

        if not file_path_str:
            return jsonify({"error": "file_path is required"}), 400

        file_path = Path(file_path_str)
        if not file_path.exists():
            return jsonify({"error": f"File not found: {file_path_str}"}), 404

        try:
            df = _read_ohlcv_file(file_path)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error loading data file %s", file_path_str)
            return jsonify({"error": f"Could not read file: {exc}"}), 500

        _state["data"] = df
        _state["data_path"] = str(file_path.resolve())

        # Summarise the loaded data for the response
        summary = _dataframe_summary(df)
        logger.info("Loaded data from %s — %d rows", file_path_str, len(df))
        return jsonify(
            {
                "message": "Data loaded successfully",
                "file": file_path.name,
                "rows": len(df),
                "columns": list(df.columns),
                "summary": summary,
            }
        )

    # -----------------------------------------------------------------------
    # Load model  (protected)
    # -----------------------------------------------------------------------

    @app.post("/api/load-model")
    @jwt_required()
    def load_model():
        """
        Load a Kronos-base predictor.

        Request body (JSON):
            {
                "model_id": "NeoQuasar/Kronos-base",
                "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
                "device": "cpu",
                "allow_stub": false
            }
        """
        body = request.get_json(silent=True) or {}
        model_id: str = str(body.get("model_id") or body.get("model_path") or _KRONOS_MODEL_ID).strip()
        tokenizer_id: str = str(body.get("tokenizer_id") or _KRONOS_TOKENIZER_ID).strip()
        device: str = body.get("device", "cpu")
        try:
            allow_stub = _request_bool(body.get("allow_stub"), default=_ALLOW_KRONOS_STUB, field="allow_stub")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422

        if not model_id:
            return jsonify({"error": "model_id is required"}), 400
        if not tokenizer_id:
            return jsonify({"error": "tokenizer_id is required"}), 400

        try:
            predictor = _load_kronos_predictor(
                model_id=model_id,
                tokenizer_id=tokenizer_id,
                device=device,
                allow_stub=allow_stub,
            )
        except ImportError as exc:
            return jsonify({"error": f"Missing dependency: {exc}"}), 500
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load Kronos predictor from %s", model_id)
            return jsonify({"error": f"Model load error: {exc}"}), 500

        _state["model"] = getattr(predictor, "model", None)
        _state["predictor"] = predictor
        _state["model_id"] = model_id
        _state["tokenizer_id"] = tokenizer_id
        _state["model_path"] = model_id
        logger.info("Kronos predictor loaded model=%s tokenizer=%s device=%s", model_id, tokenizer_id, device)
        return jsonify(
            {
                "message": "Model loaded successfully",
                "model_id": model_id,
                "tokenizer_id": tokenizer_id,
                "max_context": _KRONOS_MAX_CONTEXT,
                "device": device,
                "stub": isinstance(predictor, _StubPredictor),
            }
        )

    # -----------------------------------------------------------------------
    # Predict  (protected)
    # -----------------------------------------------------------------------

    @app.post("/api/predict")
    @jwt_required()
    def predict():
        """
        Run the Kronos model and return forecasted K-line data + a Plotly chart.

        Request body (JSON, all optional):
            {
                "horizon":        24,           // forecast steps
                "context_length": 512,          // look-back context
                "num_samples":    20            // monte-carlo samples
            }
        """
        if _state["predictor"] is None:
            return jsonify({"error": "No model loaded — call /api/load-model first"}), 400
        if _state["data"] is None:
            return jsonify({"error": "No data loaded — call /api/load-data first"}), 400

        body = request.get_json(silent=True) or {}
        try:
            horizon = _bounded_int(body.get("horizon"), default=24, minimum=1, maximum=512, field="horizon")
            context_length = _bounded_int(
                body.get("context_length", body.get("lookback")),
                default=_KRONOS_MAX_CONTEXT,
                minimum=2,
                maximum=_KRONOS_MAX_CONTEXT,
                field="context_length",
            )
            sample_count = _bounded_int(
                body.get("sample_count", body.get("num_samples")),
                default=1,
                minimum=1,
                maximum=64,
                field="sample_count",
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422

        try:
            prediction_results, actual_data = _run_prediction(
                predictor=_state["predictor"],
                df=_state["data"],
                horizon=horizon,
                context_length=context_length,
                sample_count=sample_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Prediction failed")
            return jsonify({"error": f"Prediction error: {exc}"}), 500

        # Persist results for later retrieval / save
        _state["prediction_results"] = prediction_results
        _state["actual_data"] = actual_data

        # Build chart
        chart_json = _build_chart(actual_data, prediction_results)

        # Save to disk and collect summary
        save_info = _save_prediction_results(prediction_results, actual_data)

        return jsonify(
            {
                "message": "Prediction completed",
                "horizon": horizon,
                "context_length": context_length,
                "sample_count": sample_count,
                "num_predictions": len(prediction_results),
                "predictions": prediction_results,
                "actual_data": actual_data,
                "chart": chart_json,
                "save_info": save_info,
            }
        )


# ---------------------------------------------------------------------------
# Helper: read OHLCV file
# ---------------------------------------------------------------------------

_REQUIRED_OHLCV_COLS = {"open", "high", "low", "close"}


def _read_ohlcv_file(path: Path) -> pd.DataFrame:
    """Read a CSV / Parquet / Excel file and normalise column names."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix == ".parquet":
        df = pd.read_parquet(path)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    # Normalise column names to lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    # Attempt to find and parse a date/time column
    date_candidates = [c for c in df.columns if c in ("date", "datetime", "timestamp", "timestamps", "time", "index")]
    if date_candidates:
        df[date_candidates[0]] = pd.to_datetime(df[date_candidates[0]], errors="coerce")
        df = df.set_index(date_candidates[0])
        df.index.name = "datetime"
    elif df.index.dtype == "object":
        df.index = pd.to_datetime(df.index, errors="coerce")
        df.index.name = "datetime"

    # Validate required OHLCV columns
    present = set(df.columns)
    missing = _REQUIRED_OHLCV_COLS - present
    if missing:
        raise ValueError(
            f"Data file is missing required columns: {sorted(missing)}. "
            f"Found: {sorted(present)}"
        )

    # Coerce numeric types
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=list(_REQUIRED_OHLCV_COLS))
    if isinstance(df.index, pd.DatetimeIndex):
        df = df[~df.index.isna()]
    return df


# ---------------------------------------------------------------------------
# Helper: dataframe summary
# ---------------------------------------------------------------------------

def _dataframe_summary(df: pd.DataFrame) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if "close" in df.columns:
        summary["close_min"] = float(df["close"].min())
        summary["close_max"] = float(df["close"].max())
        summary["close_last"] = float(df["close"].iloc[-1])
    if isinstance(df.index, pd.DatetimeIndex):
        summary["start"] = str(df.index[0])
        summary["end"] = str(df.index[-1])
    summary["rows"] = len(df)
    return summary


# ---------------------------------------------------------------------------
# Helper: load Kronos model
# ---------------------------------------------------------------------------

def _legacy_load_kronos_model(path: Path, device: str = "cpu") -> Any:
    """
    Load a Kronos model checkpoint.

    Tries to import the `kronos` package. Falls back to a lightweight stub
    when the package is unavailable (e.g. in a dev environment without GPU),
    so the rest of the WebUI remains functional with mock predictions.
    """
    try:
        import torch  # type: ignore[import-untyped]
        from kronos import KronosModel  # type: ignore[import-untyped]

        model = KronosModel.load(str(path), map_location=device)
        model.eval()
        return model
    except ImportError:
        logger.warning(
            "kronos or torch package not installed — using stub model for demo purposes"
        )
        return _LegacyStubModel(checkpoint_path=str(path), device=device)


class _LegacyStubModel:
    """
    Minimal stub that mimics the Kronos model interface when the real
    package is not installed.  Returns random-walk predictions so the
    entire UI pipeline can be exercised without GPU dependencies.
    """

    def __init__(self, checkpoint_path: str, device: str) -> None:
        self.checkpoint_path = checkpoint_path
        self.device = device

    def forecast(
        self,
        context: np.ndarray,
        horizon: int = 24,
        num_samples: int = 20,
    ) -> np.ndarray:
        """Return shape (num_samples, horizon, 4) — OHLC."""
        rng = np.random.default_rng(seed=42)
        last_close = float(context[-1, 3]) if context.ndim == 2 else float(context[-1])
        samples = []
        for _ in range(num_samples):
            closes = [last_close]
            for _step in range(horizon):
                closes.append(closes[-1] * (1 + rng.normal(0, 0.01)))
            step_closes = np.array(closes[1:])
            noise = np.abs(rng.normal(0, last_close * 0.005, (horizon,)))
            ohlc = np.column_stack(
                [
                    step_closes - noise,                   # open (approx)
                    step_closes + noise * 2,               # high
                    step_closes - noise * 2,               # low
                    step_closes,                           # close
                ]
            )
            samples.append(ohlc)
        return np.stack(samples, axis=0)


# ---------------------------------------------------------------------------
# Helper: run prediction
# ---------------------------------------------------------------------------

def _legacy_run_prediction(
    model: Any,
    df: pd.DataFrame,
    horizon: int,
    context_length: int,
    num_samples: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Build context window from df, call model.forecast(), return structured dicts.

    Returns
    -------
    prediction_results : list of dicts, one per step, with median OHLC + CI bands
    actual_data        : list of dicts for the context window tail (for charting)
    """
    ohlc_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    context_df = df[ohlc_cols].tail(context_length).copy()

    context_arr = context_df.to_numpy(dtype=float)  # shape (context_length, 4)

    # Generate future timestamps
    if isinstance(df.index, pd.DatetimeIndex) and len(df.index) >= 2:
        freq_delta = df.index[-1] - df.index[-2]
        future_index = [df.index[-1] + freq_delta * (i + 1) for i in range(horizon)]
    else:
        future_index = list(range(horizon))

    # --- Model inference ---
    if isinstance(model, _LegacyStubModel):
        samples = model.forecast(context_arr, horizon=horizon, num_samples=num_samples)
    else:
        try:
            import torch  # type: ignore[import-untyped]

            ctx_tensor = torch.tensor(context_arr, dtype=torch.float32).unsqueeze(0)
            with torch.no_grad():
                raw = model.forecast(ctx_tensor, horizon=horizon, num_samples=num_samples)
            # Expect (batch, samples, horizon, 4) or (samples, horizon, 4)
            samples = raw.cpu().numpy()
            if samples.ndim == 4:
                samples = samples[0]  # drop batch dim → (samples, horizon, 4)
        except Exception as exc:  # noqa: BLE001
            logger.error("Torch inference failed: %s — falling back to stub", exc)
            stub = _LegacyStubModel(checkpoint_path="", device="cpu")
            samples = stub.forecast(context_arr, horizon=horizon, num_samples=num_samples)

    # --- Summarise samples into prediction dicts ---
    prediction_results: list[dict[str, Any]] = []
    for step_idx in range(horizon):
        step_samples = samples[:, step_idx, :]  # (num_samples, 4)
        ts = future_index[step_idx]
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        median_ohlc = np.median(step_samples, axis=0)
        p10_ohlc = np.percentile(step_samples, 10, axis=0)
        p90_ohlc = np.percentile(step_samples, 90, axis=0)

        prediction_results.append(
            {
                "timestamp": ts_str,
                "open": float(median_ohlc[0]),
                "high": float(median_ohlc[1]),
                "low": float(median_ohlc[2]),
                "close": float(median_ohlc[3]),
                "close_p10": float(p10_ohlc[3]),
                "close_p90": float(p90_ohlc[3]),
            }
        )

    # --- Build actual_data tail ---
    actual_data: list[dict[str, Any]] = []
    tail_df = context_df.tail(min(100, len(context_df)))
    for ts, row in tail_df.iterrows():
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        actual_data.append(
            {
                "timestamp": ts_str,
                "open": float(row.get("open", row.iloc[0])),
                "high": float(row.get("high", row.iloc[1])),
                "low": float(row.get("low", row.iloc[2])),
                "close": float(row.get("close", row.iloc[3])),
            }
        )

    return prediction_results, actual_data


def _load_kronos_predictor(
    *,
    model_id: str,
    tokenizer_id: str,
    device: str = "cpu",
    allow_stub: bool = False,
) -> Any:
    """Load Kronos-base through the upstream KronosPredictor API."""
    _ensure_kronos_import_path()
    try:
        from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore[import-untyped]
    except ImportError as exc:
        if allow_stub and not _IS_PRODUCTION:
            logger.warning("Kronos package unavailable; using explicit dev/test stub predictor")
            return _StubPredictor(model_id=model_id, tokenizer_id=tokenizer_id, device=device)
        raise ImportError("Kronos model package is not installed") from exc

    tokenizer = KronosTokenizer.from_pretrained(tokenizer_id)
    model = Kronos.from_pretrained(model_id)
    if hasattr(model, "eval"):
        model.eval()
    return KronosPredictor(model, tokenizer, device=device, max_context=_KRONOS_MAX_CONTEXT)


class _StubPredictor:
    """Explicit dev/test predictor with the same predict() shape as KronosPredictor."""

    def __init__(self, model_id: str, tokenizer_id: str, device: str) -> None:
        self.model = None
        self.model_id = model_id
        self.tokenizer_id = tokenizer_id
        self.device = device

    def predict(
        self,
        df: pd.DataFrame,
        x_timestamp: pd.Series,
        y_timestamp: pd.Series,
        pred_len: int,
        sample_count: int = 1,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed=42)
        last_close = float(df["close"].iloc[-1])
        closes = []
        current = last_close
        for _ in range(pred_len):
            current = current * (1 + rng.normal(0, 0.01))
            closes.append(current)

        close_arr = np.array(closes, dtype=float)
        noise = np.abs(rng.normal(0, last_close * 0.005, pred_len))
        result = pd.DataFrame(
            {
                "open": close_arr - noise,
                "high": close_arr + noise * 2,
                "low": close_arr - noise * 2,
                "close": close_arr,
            }
        )
        if "volume" in df.columns:
            result["volume"] = float(df["volume"].tail(min(len(df), 20)).mean())
        if "amount" in df.columns:
            result["amount"] = float(df["amount"].tail(min(len(df), 20)).mean())
        result.index = pd.Index(y_timestamp.iloc[:pred_len], name="datetime")
        return result


def _timestamp_series_for_df(df: pd.DataFrame) -> pd.Series:
    if isinstance(df.index, pd.DatetimeIndex):
        return pd.Series(df.index, index=df.index)
    return pd.Series(pd.RangeIndex(start=0, stop=len(df), step=1), index=df.index)


def _future_timestamps(x_timestamp: pd.Series, horizon: int) -> pd.Series:
    if len(x_timestamp) >= 2 and isinstance(x_timestamp.iloc[-1], pd.Timestamp):
        freq_delta = x_timestamp.iloc[-1] - x_timestamp.iloc[-2]
        if pd.isna(freq_delta) or freq_delta == pd.Timedelta(0):
            freq_delta = pd.Timedelta(minutes=5)
        return pd.Series([x_timestamp.iloc[-1] + freq_delta * (i + 1) for i in range(horizon)])
    start = int(x_timestamp.iloc[-1]) + 1 if len(x_timestamp) else 0
    return pd.Series(range(start, start + horizon))


def _records_from_frame(df: pd.DataFrame, timestamp_fallback: pd.Series) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for idx, (_, row) in enumerate(df.iterrows()):
        ts = df.index[idx] if not isinstance(df.index, pd.RangeIndex) else timestamp_fallback.iloc[idx]
        item: dict[str, Any] = {"timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts)}
        for col in ("open", "high", "low", "close", "volume", "amount", "close_p10", "close_p90"):
            if col in row and pd.notna(row[col]):
                item[col] = float(row[col])
        records.append(item)
    return records


def _run_prediction(
    predictor: Any,
    df: pd.DataFrame,
    horizon: int,
    context_length: int,
    sample_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build Kronos predictor inputs, call predict(), and serialize the result."""
    input_cols = [c for c in ("open", "high", "low", "close", "volume", "amount") if c in df.columns]
    context_df = df[input_cols].tail(min(context_length, _KRONOS_MAX_CONTEXT)).copy()
    if len(context_df) < 2:
        raise ValueError("At least 2 context rows are required for prediction")

    x_timestamp = _timestamp_series_for_df(context_df)
    y_timestamp = _future_timestamps(x_timestamp, horizon)
    pred_df = predictor.predict(
        df=context_df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=horizon,
        sample_count=sample_count,
    )
    if "close" in pred_df.columns:
        if "close_p10" not in pred_df.columns:
            pred_df["close_p10"] = pred_df["close"]
        if "close_p90" not in pred_df.columns:
            pred_df["close_p90"] = pred_df["close"]

    prediction_results = _records_from_frame(pred_df, timestamp_fallback=y_timestamp)
    actual_tail = context_df.tail(min(100, len(context_df)))
    actual_timestamps = x_timestamp.tail(len(actual_tail)).reset_index(drop=True)
    actual_data = _records_from_frame(actual_tail, timestamp_fallback=actual_timestamps)
    return prediction_results, actual_data


# ---------------------------------------------------------------------------
# Helper: build Plotly chart JSON
# ---------------------------------------------------------------------------

def _build_chart(
    actual_data: list[dict[str, Any]],
    prediction_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a Plotly figure as a JSON-serialisable dict."""
    fig = go.Figure()

    # Actual candlesticks
    if actual_data:
        fig.add_trace(
            go.Candlestick(
                x=[d["timestamp"] for d in actual_data],
                open=[d["open"] for d in actual_data],
                high=[d["high"] for d in actual_data],
                low=[d["low"] for d in actual_data],
                close=[d["close"] for d in actual_data],
                name="Actual",
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
            )
        )

    # Predicted candlesticks
    if prediction_results:
        fig.add_trace(
            go.Candlestick(
                x=[d["timestamp"] for d in prediction_results],
                open=[d["open"] for d in prediction_results],
                high=[d["high"] for d in prediction_results],
                low=[d["low"] for d in prediction_results],
                close=[d["close"] for d in prediction_results],
                name="Forecast (median)",
                increasing_line_color="#29b6f6",
                decreasing_line_color="#ce93d8",
            )
        )

        # Confidence band (P10–P90)
        xs_fwd = [d["timestamp"] for d in prediction_results]
        xs_rev = list(reversed(xs_fwd))
        ys_p90 = [d["close_p90"] for d in prediction_results]
        ys_p10_rev = list(reversed([d["close_p10"] for d in prediction_results]))

        fig.add_trace(
            go.Scatter(
                x=xs_fwd + xs_rev,
                y=ys_p90 + ys_p10_rev,
                fill="toself",
                fillcolor="rgba(41, 182, 246, 0.15)",
                line={"color": "rgba(255,255,255,0)"},
                hoverinfo="skip",
                showlegend=True,
                name="80% CI",
            )
        )

    fig.update_layout(
        title="Kronos K-line Forecast",
        xaxis_title="Time",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 60, "r": 20, "t": 60, "b": 60},
    )

    return json.loads(fig.to_json())


# ---------------------------------------------------------------------------
# Helper: save prediction results
# ---------------------------------------------------------------------------

def _save_prediction_results(
    prediction_results: list[dict[str, Any]],
    actual_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Persist prediction results to a JSON file in ./results/.

    BUG FIX: The original code had a scope error where `last_pred` could be
    used before it was assigned when `prediction_results` was empty.  This
    implementation fully guards against that case.

    Returns a dict with save metadata.
    """
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    timestamp_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = results_dir / f"prediction_{timestamp_tag}.json"

    # --- Build comparison stats only when both arrays are non-empty ---
    comparison: dict[str, Any] = {}

    if prediction_results and actual_data:
        # Both are available — safe to access prediction_results[0]
        last_pred = prediction_results[0]
        first_actual = actual_data[0]

        comparison = {
            "first_forecast_close": last_pred["close"],
            "first_actual_close": first_actual["close"],
            "delta": last_pred["close"] - first_actual["close"],
            "delta_pct": (
                (last_pred["close"] - first_actual["close"]) / first_actual["close"] * 100
                if first_actual["close"] != 0
                else None
            ),
        }
    elif prediction_results and not actual_data:
        # Only predictions available
        comparison = {
            "first_forecast_close": prediction_results[0]["close"],
            "note": "No actual data to compare against",
        }
    # else: neither — comparison stays empty {}

    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "prediction_count": len(prediction_results),
        "actual_count": len(actual_data),
        "comparison": comparison,
        "predictions": prediction_results,
        "actuals": actual_data,
    }

    try:
        out_file.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.info("Saved prediction results to %s", out_file)
        return {"saved": True, "path": str(out_file), "comparison": comparison}
    except OSError as exc:
        logger.error("Could not write results file: %s", exc)
        return {"saved": False, "error": str(exc), "comparison": comparison}


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV", "production").lower() == "development"
    logger.info("Starting Kronos WebUI on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)

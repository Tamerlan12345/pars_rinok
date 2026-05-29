"""
conftest.py — Shared pytest fixtures for Kronos WebUI tests.
"""
import sys
import os
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

# Make webui importable
WEBUI_DIR = Path(__file__).parent.parent / "webui"
sys.path.insert(0, str(WEBUI_DIR))

# Patch heavy optional deps before import
import unittest.mock as mock

# Stub out torch / Kronos model so tests run without GPU/HuggingFace downloads
sys.modules.setdefault("torch", mock.MagicMock())
sys.modules.setdefault("safetensors", mock.MagicMock())
sys.modules.setdefault("huggingface_hub", mock.MagicMock())
sys.modules.setdefault("tqdm", mock.MagicMock())
sys.modules.setdefault("plotly", mock.MagicMock())
sys.modules.setdefault("plotly.graph_objects", mock.MagicMock())
sys.modules.setdefault("plotly.utils", mock.MagicMock())

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_PASSWORD", "testpass123")
os.environ.setdefault("GEMINI_API_KEY", "")


@pytest.fixture(scope="session")
def sample_ohlcv_df():
    """100-row OHLCV DataFrame with timestamps."""
    n = 200
    rng = np.random.default_rng(42)
    price = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({
        "timestamps": pd.date_range("2024-01-01", periods=n, freq="5min"),
        "open":   price,
        "high":   price + rng.uniform(0.1, 1.0, n),
        "low":    price - rng.uniform(0.1, 1.0, n),
        "close":  price + rng.normal(0, 0.3, n),
        "volume": rng.integers(1000, 50000, n).astype(float),
        "amount": rng.uniform(100_000, 5_000_000, n),
    })
    return df


@pytest.fixture(scope="session")
def sample_csv_path(tmp_path_factory, sample_ohlcv_df):
    """Write sample OHLCV data to a temp CSV and return its path."""
    p = tmp_path_factory.mktemp("data") / "test_data.csv"
    sample_ohlcv_df.to_csv(p, index=False)
    return str(p)


@pytest.fixture
def flask_app():
    """Flask test application with test config."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False  # tokens never expire in tests
    return app


@pytest.fixture
def client(flask_app):
    """Flask test client."""
    return flask_app.test_client()


@pytest.fixture
def auth_headers(client):
    """Login and return Authorization header dict with valid JWT."""
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": os.environ["ADMIN_PASSWORD"]},
        content_type="application/json",
    )
    assert resp.status_code == 200, f"Login failed: {resp.get_json()}"
    token = resp.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

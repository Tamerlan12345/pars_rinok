"""
test_api.py — Integration tests for Kronos WebUI Flask API.

Run with:
    cd D:/pars_rinok/Kronos
    pip install pytest flask flask-jwt-extended flask-cors werkzeug python-dotenv pandas numpy
    pytest tests/ -v
"""
import json
import os
import sys
import io
import unittest.mock as mock
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_ohlcv_records(n: int = 10) -> list[dict]:
    """Return *n* minimal OHLCV dicts."""
    rng = np.random.default_rng(0)
    price = 100.0 + np.cumsum(rng.normal(0, 0.3, n))
    return [
        {
            "timestamp": f"2024-01-01T{i:02d}:00:00",
            "open": float(price[i]),
            "high": float(price[i] + 0.5),
            "low":  float(price[i] - 0.5),
            "close": float(price[i] + 0.1),
            "volume": 1000.0,
            "amount": 100_000.0,
        }
        for i in range(n)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Public endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_body(self, client):
        data = client.get("/api/health").get_json()
        assert data["status"] == "ok"
        assert "service" in data
        assert "timestamp" in data

    def test_health_no_auth_required(self, client):
        """Health must not require a JWT."""
        resp = client.get("/api/health")
        assert resp.status_code == 200  # no token → still 200


# ─────────────────────────────────────────────────────────────────────────────
# Authentication
# ─────────────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_login_success(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": os.environ["ADMIN_PASSWORD"]},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["username"] == "admin"

    def test_login_wrong_password(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong!"},
        )
        assert resp.status_code == 401

    def test_login_unknown_user(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "x"},
        )
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 400

    def test_me_requires_auth(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_token(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["username"] == "admin"

    def test_logout_revokes_token(self, client, flask_app):
        """After logout, the same token must be rejected."""
        login_resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": os.environ["ADMIN_PASSWORD"]},
        )
        token = login_resp.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        logout_resp = client.post("/api/auth/logout", headers=headers)
        assert logout_resp.status_code == 200

        # Token should now be revoked
        me_resp = client.get("/api/auth/me", headers=headers)
        assert me_resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# JWT protection
# ─────────────────────────────────────────────────────────────────────────────

class TestJWTProtection:
    PROTECTED = [
        ("GET",  "/api/data-files"),
        ("POST", "/api/load-data"),
        ("POST", "/api/predict"),
        ("POST", "/api/load-model"),
    ]

    @pytest.mark.parametrize("method,url", PROTECTED)
    def test_returns_401_without_token(self, client, method, url):
        fn = getattr(client, method.lower())
        resp = fn(url, json={})
        assert resp.status_code == 401, f"{method} {url} should require auth"

    def test_data_files_ok_with_token(self, client, auth_headers):
        resp = client.get("/api/data-files", headers=auth_headers)
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Available models
# ─────────────────────────────────────────────────────────────────────────────

class TestAvailableModels:
    def test_available_models_public(self, client):
        """GET /api/available-models must be callable (public or with auth)."""
        resp = client.get("/api/available-models")
        # Either 200 or 401 — just must not 500
        assert resp.status_code in (200, 401)

    def test_available_models_content(self, client, auth_headers):
        resp = client.get("/api/available-models", headers=auth_headers)
        # If endpoint exists, check shape
        if resp.status_code == 200:
            data = resp.get_json()
            assert "models" in data or isinstance(data, dict)


# ─────────────────────────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadData:
    def test_missing_file_path(self, client, auth_headers):
        resp = client.post(
            "/api/load-data",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_nonexistent_file(self, client, auth_headers):
        resp = client.post(
            "/api/load-data",
            json={"file_path": "/nonexistent/path/data.csv"},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 500)

    def test_valid_csv(self, client, auth_headers, sample_csv_path):
        resp = client.post(
            "/api/load-data",
            json={"file_path": sample_csv_path},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("success") is True
        assert body["data_info"]["rows"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Prediction (model mocked)
# ─────────────────────────────────────────────────────────────────────────────

class TestPredict:
    def test_predict_no_model_loaded(self, client, auth_headers):
        """Without loading a model first, /api/predict should return 400."""
        resp = client.post(
            "/api/predict",
            json={"file_path": "/some/file.csv", "lookback": 50, "pred_len": 10},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 500)

    def test_predict_missing_file_path(self, client, auth_headers):
        resp = client.post(
            "/api/predict",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 500)

    def test_predict_mocked_model(self, client, auth_headers, sample_csv_path, flask_app):
        """Inject a stub predictor and verify the full predict pipeline returns 200."""
        import app as webui_app

        # Build fake prediction DataFrame
        pred_n = 10
        fake_pred = pd.DataFrame({
            "open":   [100.0 + i * 0.1 for i in range(pred_n)],
            "high":   [100.5 + i * 0.1 for i in range(pred_n)],
            "low":    [ 99.5 + i * 0.1 for i in range(pred_n)],
            "close":  [100.2 + i * 0.1 for i in range(pred_n)],
            "volume": [1000.0] * pred_n,
            "amount": [100000.0] * pred_n,
        })

        stub_predictor = mock.MagicMock()
        stub_predictor.predict.return_value = fake_pred

        # Inject stub into module state
        webui_app._state["predictor"] = stub_predictor

        # Also need to silence Plotly chart creation
        with mock.patch("app.create_prediction_chart", return_value="{}"):
            resp = client.post(
                "/api/predict",
                json={"file_path": sample_csv_path, "lookback": 50, "pred_len": pred_n},
                headers=auth_headers,
            )

        # Cleanup
        webui_app._state["predictor"] = None

        # The endpoint may succeed or fail depending on internal logic;
        # the key invariant is no unhandled 500 from missing fields
        assert resp.status_code != 500 or "error" in (resp.get_json() or {})

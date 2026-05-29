"""
test_data_utils.py — Unit tests for data-loading and time-detection utilities
extracted from webui/app.py.

These tests do NOT require the Kronos model or GPU.
"""
import sys
import os
from pathlib import Path
import unittest.mock as mock

import pandas as pd
import numpy as np
import pytest

# Make webui importable
WEBUI_DIR = Path(__file__).parent.parent / "webui"
sys.path.insert(0, str(WEBUI_DIR))

# Stub heavy deps
for mod in ("torch", "safetensors", "huggingface_hub", "tqdm",
            "plotly", "plotly.graph_objects", "plotly.utils"):
    sys.modules.setdefault(mod, mock.MagicMock())

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_PASSWORD", "testpass123")
os.environ.setdefault("GEMINI_API_KEY", "")

import app as webui_app


# ─────────────────────────────────────────────────────────────────────────────
# detect_timeframe (inner helper, accessed via load-data endpoint logic)
# ─────────────────────────────────────────────────────────────────────────────

def _make_df(freq: str, n: int = 20) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamps": pd.date_range("2024-01-01", periods=n, freq=freq),
        "open":   np.ones(n) * 100,
        "high":   np.ones(n) * 101,
        "low":    np.ones(n) * 99,
        "close":  np.ones(n) * 100,
        "volume": np.ones(n) * 1000,
    })


class TestLoadDataFile:
    """Tests for webui_app.load_data_file()"""

    def test_valid_csv_returns_df(self, tmp_path):
        df = _make_df("5min")
        p = tmp_path / "data.csv"
        df.to_csv(p, index=False)
        result, err = webui_app.load_data_file(str(p))
        assert err is None
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 20

    def test_missing_ohlc_columns(self, tmp_path):
        df = pd.DataFrame({"timestamps": pd.date_range("2024-01-01", periods=5, freq="1h"),
                           "volume": [1, 2, 3, 4, 5]})
        p = tmp_path / "bad.csv"
        df.to_csv(p, index=False)
        result, err = webui_app.load_data_file(str(p))
        assert result is None
        assert err is not None

    def test_nonexistent_file(self):
        result, err = webui_app.load_data_file("/nonexistent/path/data.csv")
        assert result is None
        assert err is not None

    def test_no_timestamp_col_creates_one(self, tmp_path):
        """If no timestamp column, a synthetic one should be created."""
        df = pd.DataFrame({
            "open":  [100.0, 101.0],
            "high":  [102.0, 103.0],
            "low":   [ 99.0, 100.0],
            "close": [100.5, 101.5],
        })
        p = tmp_path / "notimestamp.csv"
        df.to_csv(p, index=False)
        result, err = webui_app.load_data_file(str(p))
        assert err is None
        assert "timestamps" in result.columns

    def test_date_col_renamed_to_timestamps(self, tmp_path):
        df = pd.DataFrame({
            "date":  ["2024-01-01", "2024-01-02"],
            "open":  [100.0, 101.0],
            "high":  [102.0, 103.0],
            "low":   [ 99.0, 100.0],
            "close": [100.5, 101.5],
        })
        p = tmp_path / "withdate.csv"
        df.to_csv(p, index=False)
        result, err = webui_app.load_data_file(str(p))
        assert err is None
        assert "timestamps" in result.columns

    def test_string_prices_coerced_to_float(self, tmp_path):
        df = pd.DataFrame({
            "timestamps": pd.date_range("2024-01-01", periods=3, freq="1h"),
            "open":  ["100.1", "101.2", "102.3"],
            "high":  ["101.1", "102.2", "103.3"],
            "low":   [ "99.1", "100.2", "101.3"],
            "close": ["100.5", "101.5", "102.5"],
        })
        p = tmp_path / "strings.csv"
        df.to_csv(p, index=False)
        result, err = webui_app.load_data_file(str(p))
        assert err is None
        assert result["open"].dtype == float

    def test_nan_rows_dropped(self, tmp_path):
        df = _make_df("1h", n=10)
        df.loc[3, "close"] = float("nan")
        p = tmp_path / "withnan.csv"
        df.to_csv(p, index=False)
        result, err = webui_app.load_data_file(str(p))
        assert err is None
        assert len(result) == 9  # one row dropped

    def test_optional_volume_column(self, tmp_path):
        df = pd.DataFrame({
            "timestamps": pd.date_range("2024-01-01", periods=5, freq="1h"),
            "open":  [100.0] * 5,
            "high":  [101.0] * 5,
            "low":   [ 99.0] * 5,
            "close": [100.5] * 5,
            # no volume or amount
        })
        p = tmp_path / "novol.csv"
        df.to_csv(p, index=False)
        result, err = webui_app.load_data_file(str(p))
        assert err is None


# ─────────────────────────────────────────────────────────────────────────────
# Gemini module (mocked)
# ─────────────────────────────────────────────────────────────────────────────

class TestGeminiAnalyst:
    """Tests for GeminiAnalyst without a real API key."""

    @pytest.fixture(autouse=True)
    def patch_genai(self):
        """Provide a mock genai module."""
        with mock.patch.dict(sys.modules, {
            "google": mock.MagicMock(),
            "google.generativeai": mock.MagicMock(),
        }):
            # Re-import gemini with patched deps
            if "gemini" in sys.modules:
                del sys.modules["gemini"]
            import gemini as gemini_mod
            self.gemini_mod = gemini_mod
            yield gemini_mod

    def test_mock_mode_no_api_key(self):
        analyst = self.gemini_mod.GeminiAnalyst(api_key="")
        result = analyst.analyze_prediction(
            historical_data=[{"open": 100, "close": 101, "high": 102, "low": 99}],
            prediction_data=[{"open": 102, "close": 103, "high": 104, "low": 101}],
            symbol="TEST",
        )
        assert isinstance(result, str)
        assert len(result) > 0  # returns mock text

    def test_analyze_prediction_returns_string(self):
        """With a mock API key, calls Gemini mock and returns string."""
        mock_response = mock.MagicMock()
        mock_response.text = "Bullish trend ahead. Key resistance at 105."

        analyst = self.gemini_mod.GeminiAnalyst.__new__(self.gemini_mod.GeminiAnalyst)
        analyst._mock_mode = False
        analyst._model = mock.MagicMock()
        analyst._model.generate_content.return_value = mock_response

        result = analyst._call_with_retry("some prompt")
        assert result == "Bullish trend ahead. Key resistance at 105."

    def test_analyze_comparison_returns_string(self):
        mock_response = mock.MagicMock()
        mock_response.text = "Prediction was accurate within 2%."

        analyst = self.gemini_mod.GeminiAnalyst.__new__(self.gemini_mod.GeminiAnalyst)
        analyst._mock_mode = False
        analyst._model = mock.MagicMock()
        analyst._model.generate_content.return_value = mock_response

        prediction_data = [{"open": 100, "close": 101, "high": 102, "low": 99}]
        actual_data = [{"open": 101, "close": 102, "high": 103, "low": 100}]
        result = analyst.analyze_comparison(prediction_data, actual_data)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_retry_on_exception(self):
        """If Gemini raises, it should retry up to _MAX_RETRIES times."""
        analyst = self.gemini_mod.GeminiAnalyst.__new__(self.gemini_mod.GeminiAnalyst)
        analyst._mock_mode = False
        analyst._model = mock.MagicMock()
        analyst._model.generate_content.side_effect = RuntimeError("API error")

        with pytest.raises(RuntimeError):
            with mock.patch("time.sleep"):  # don't actually sleep in tests
                analyst._call_with_retry("prompt")

        assert analyst._model.generate_content.call_count == self.gemini_mod._MAX_RETRIES


# ─────────────────────────────────────────────────────────────────────────────
# Model state helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestAppState:
    def test_initial_state_all_none(self):
        assert webui_app._state["model"] is None
        assert webui_app._state["data"] is None

    def test_prediction_results_initially_empty(self):
        assert webui_app._state["prediction_results"] == []

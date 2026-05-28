"""
Centras Tokenizer — proprietary OHLCV tokenization service.

Conceptually inspired by the hierarchical discretization approach explored in
financial time-series tokenization research (NeurIPS 2024 domain).
Implementation is entirely original — no third-party tokenizer source code used.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field

# Vocabulary sizes — chosen so coarse*fine = 256 unique joint tokens.
N_COARSE: int = 32   # coarse vocabulary: captures trend direction and magnitude
N_FINE: int = 8      # fine sub-tokens per coarse bin: captures volatility detail


class TokenizationError(ValueError):
    """Exception raised when tokenization fails due to invalid input data."""


@dataclass
class TokenizedSequence:
    coarse_tokens: list[int]
    fine_tokens: list[int]
    n_candles: int
    normalization_stats: dict = field(default_factory=dict)
    # Keys: mean, std, lo, hi — all float, describe the log-return distribution.


def tokenize_ohlcv(candles: list[dict]) -> TokenizedSequence:
    """
    Convert a sequence of OHLCV dicts to a hierarchical discrete token sequence.

    Algorithm:
      1. Extract close prices and compute ln(P_t / P_{t-1}) log returns.
      2. Winsorize at ±3σ to suppress fat-tail outliers without discarding them entirely.
      3. Min-max normalize the winsorized series to [0, 1].
      4. Coarse quantization: floor(normalized * N_COARSE) → 32 bins, one per return.
      5. Fine quantization: residual within the coarse bin → 8 sub-bins.

    Args:
        candles: list of dicts with keys: open, high, low, close, volume, timestamp.
                 Must have at least 2 elements (need at least one log return).

    Returns:
        TokenizedSequence with len(coarse_tokens) == len(fine_tokens) == len(candles) - 1.

    Raises:
        TokenizationError: if fewer than 2 candles are provided or close prices are invalid.
    """
    if len(candles) < 2:
        raise TokenizationError(f"tokenize_ohlcv requires at least 2 candles, received {len(candles)}")

    closes = np.array([c["close"] for c in candles], dtype=np.float64)

    if np.any(closes <= 0):
        bad = int(np.sum(closes <= 0))
        raise TokenizationError(f"Close prices must be positive; found {bad} non-positive value(s)")

    log_returns = np.log(closes[1:] / closes[:-1])

    mean = float(np.mean(log_returns))
    std = float(np.std(log_returns))
    # Guard against std == 0 (flat price series): treat all returns as identical.
    if std < 1e-12:
        std = 1e-8

    # Winsorize at 3σ — keeps the series bounded without hard-zero clipping.
    log_returns_clipped = np.clip(log_returns, mean - 3.0 * std, mean + 3.0 * std)

    lo = float(log_returns_clipped.min())
    hi = float(log_returns_clipped.max())
    span = hi - lo
    if span < 1e-12:
        # All returns identical after winsorization — map everything to bin 0.
        span = 1e-8

    normalized = (log_returns_clipped - lo) / span  # [0.0, 1.0]

    # Coarse bins: [0, N_COARSE - 1]
    coarse = np.floor(normalized * N_COARSE).astype(np.int32)
    coarse = np.clip(coarse, 0, N_COARSE - 1)

    # Residual within coarse bin, scaled to [0, 1) within the bin width.
    coarse_lower_edge = coarse.astype(np.float64) / N_COARSE
    residual_within_bin = (normalized - coarse_lower_edge) * N_COARSE  # [0.0, 1.0)

    fine = np.floor(residual_within_bin * N_FINE).astype(np.int32)
    fine = np.clip(fine, 0, N_FINE - 1)

    return TokenizedSequence(
        coarse_tokens=coarse.tolist(),
        fine_tokens=fine.tolist(),
        n_candles=len(candles),
        normalization_stats={
            "mean": mean,
            "std": std,
            "lo": lo,
            "hi": hi,
        },
    )


def tokens_to_prompt_repr(seq: TokenizedSequence, ticker: str, period: str) -> str:
    """
    Serialize a TokenizedSequence to a compact, LLM-readable string.

    The representation is designed to fit in a single prompt block while
    providing enough context for the model to reason about trend and volatility.
    Token lists are truncated to 500 characters each to control prompt size.
    """
    coarse_str = ",".join(str(t) for t in seq.coarse_tokens)
    fine_str = ",".join(str(t) for t in seq.fine_tokens)

    # Hard limit — prevents runaway prompts on very long histories.
    max_chars = 500
    if len(coarse_str) > max_chars:
        coarse_str = coarse_str[:max_chars] + "...[truncated]"
    if len(fine_str) > max_chars:
        fine_str = fine_str[:max_chars] + "...[truncated]"

    stats = seq.normalization_stats
    return (
        f"Ticker: {ticker} | Period: {period} | Candles: {seq.n_candles}\n"
        f"Coarse tokens (trend direction/magnitude, range 0-{N_COARSE - 1}): [{coarse_str}]\n"
        f"Fine tokens (intra-bin volatility detail, range 0-{N_FINE - 1}): [{fine_str}]\n"
        f"Normalization stats: mean={stats.get('mean', 0):.6f}, "
        f"std={stats.get('std', 0):.6f}, "
        f"lo={stats.get('lo', 0):.6f}, "
        f"hi={stats.get('hi', 0):.6f}"
    )

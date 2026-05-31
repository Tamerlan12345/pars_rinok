"""Analysis router — AI-powered OHLCV tokenization + Gemini analysis."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analysis import Analysis
from app.models.candle import Candle
from app.models.news import NewsItem
from app.routers.auth import get_current_user
from app.schemas.analysis import AnalysisRead, AnalysisRequest, AnalysisResponse
from app.services.gemini_client import analyze_with_gemini
from app.services.logger_service import log_event
from app.services.tokenizer import TokenizationError, tokenize_ohlcv, tokens_to_prompt_repr

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/run", response_model=AnalysisResponse)
async def run_analysis(
    body: AnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
) -> AnalysisResponse:
    # Step 1: load candles from DB
    result = await db.execute(
        select(Candle)
        .where(Candle.ticker_symbol == body.ticker, Candle.interval == body.interval)
        .order_by(desc(Candle.timestamp))
        .limit(512)
    )
    candles = list(reversed(result.scalars().all()))

    if len(candles) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Not enough candles for {body.ticker} ({body.interval}). "
                "Fetch market data first via /api/market/fetch."
            ),
        )

    candle_dicts = [
        {"open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume, "timestamp": c.timestamp}
        for c in candles
    ]

    # Step 2: tokenize
    try:
        token_seq = tokenize_ohlcv(candle_dicts)
    except TokenizationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    token_repr = tokens_to_prompt_repr(token_seq, body.ticker, body.period)

    # Step 3: recent news as context for Gemini
    news_result = await db.execute(
        select(NewsItem.title)
        .where(NewsItem.ticker_symbol == body.ticker)
        .order_by(desc(NewsItem.published_at))
        .limit(5)
    )
    recent_headlines = [row[0] for row in news_result.all()]

    # Step 4: Gemini analysis
    current_price = candles[-1].close if candles else 0.0
    gemini_result = await analyze_with_gemini(
        token_repr, 
        body.ticker, 
        recent_headlines, 
        current_price=float(current_price), 
        forecast_horizon=body.forecast_horizon
    )
    mock_mode = gemini_result.get("mock_mode", False)

    # Step 5: persist analysis
    analysis = Analysis(
        ticker_symbol=body.ticker,
        period=body.period,
        interval=body.interval,
        candle_count=len(candles),
        tokens_coarse=token_seq.coarse_tokens,
        tokens_fine=token_seq.fine_tokens,
        gemini_summary=gemini_result.get("summary"),
        gemini_signals=gemini_result.get("signals", []),
        gemini_sentiment=gemini_result.get("sentiment"),
        gemini_confidence=gemini_result.get("confidence"),
        gemini_key_levels=gemini_result.get("key_levels", []),
        gemini_risk_factors=gemini_result.get("risk_factors", []),
        forecast_direction=gemini_result.get("forecast_direction"),
        forecast_price_target=gemini_result.get("forecast_price_target"),
        forecast_period=gemini_result.get("forecast_period"),
        forecast_rationale=gemini_result.get("forecast_rationale"),
        mock_mode=mock_mode,
    )
    db.add(analysis)
    await db.flush()

    # Step 6: log event
    await log_event(
        db=db,
        level="INFO",
        event="analysis.completed",
        message=f"Analysis for {body.ticker} ({body.period}/{body.interval}): {gemini_result.get('sentiment')} mock={mock_mode}",
        context={
            "ticker": body.ticker,
            "candle_count": len(candles),
            "sentiment": gemini_result.get("sentiment"),
            "confidence": gemini_result.get("confidence"),
            "mock_mode": mock_mode,
            "analysis_id": analysis.id,
        },
    )

    return AnalysisResponse(
        id=analysis.id,
        ticker_symbol=analysis.ticker_symbol,
        period=analysis.period,
        interval=analysis.interval,
        candle_count=analysis.candle_count,
        tokens_coarse=analysis.tokens_coarse,
        tokens_fine=analysis.tokens_fine,
        gemini_summary=analysis.gemini_summary,
        gemini_signals=analysis.gemini_signals,
        gemini_sentiment=analysis.gemini_sentiment,
        gemini_confidence=analysis.gemini_confidence,
        gemini_key_levels=analysis.gemini_key_levels,
        gemini_risk_factors=analysis.gemini_risk_factors,
        forecast_direction=analysis.forecast_direction,
        forecast_price_target=analysis.forecast_price_target,
        forecast_period=analysis.forecast_period,
        forecast_rationale=analysis.forecast_rationale,
        mock_mode=analysis.mock_mode,
        created_at=analysis.created_at,
        message="Анализ завершён" if not mock_mode else "Анализ завершён (демо-режим — настройте GEMINI_API_KEY)",
    )


@router.get("/history", response_model=list[AnalysisRead])
async def get_analysis_history(
    ticker: str = Query(...),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[AnalysisRead]:
    ticker = ticker.upper().strip()
    result = await db.execute(
        select(Analysis)
        .where(Analysis.ticker_symbol == ticker)
        .order_by(desc(Analysis.created_at))
        .limit(limit)
    )
    analyses = result.scalars().all()
    return [AnalysisRead.model_validate(a) for a in analyses]


@router.get("/{analysis_id}", response_model=AnalysisRead)
async def get_analysis(
    analysis_id: int,
    db: AsyncSession = Depends(get_db),
) -> AnalysisRead:
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return AnalysisRead.model_validate(analysis)

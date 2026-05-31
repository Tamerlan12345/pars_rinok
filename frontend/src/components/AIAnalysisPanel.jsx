import { useState, useEffect, useCallback } from 'react'
import { analysisApi } from '../api/client.js'
import TokenizerVisual from './TokenizerVisual.jsx'
import { formatDistanceToNow } from 'date-fns'
import { ru } from 'date-fns/locale'

const PERIODS = ['1d', '5d', '1mo', '3mo', '6mo', '1y']
const INTERVALS = ['1m', '5m', '15m', '1h', '1d']

const SENTIMENT_LABEL = { bullish: 'Бычий', bearish: 'Медвежий', neutral: 'Нейтральный' }
const SENTIMENT_ICON  = { bullish: '▲', bearish: '▼', neutral: '►' }
const SIGNAL_TYPE_RU  = { momentum: 'Импульс', reversal: 'Разворот', breakout: 'Пробой', consolidation: 'Консолидация' }
const SIGNAL_STR_RU   = { weak: 'Слабый', moderate: 'Умеренный', strong: 'Сильный' }
const FORECAST_DIR_RU = { up: 'Рост', down: 'Снижение', sideways: 'Боковик' }
const FORECAST_DIR_COLOR = { up: 'var(--success)', down: 'var(--error)', sideways: 'var(--warning)' }
const FORECAST_DIR_ICON  = { up: '↑', down: '↓', sideways: '↔' }

function ConfidenceBar({ pct }) {
  const color = pct >= 70 ? 'var(--success)' : pct >= 45 ? 'var(--warning)' : 'var(--error)'
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Уверенность модели
        </span>
        <span style={{ fontSize: '15px', fontWeight: '700', color }}>{pct}%</span>
      </div>
      <div style={{ height: '6px', background: 'var(--bg-tertiary)', borderRadius: '3px', overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: `${pct}%`,
          background: `linear-gradient(90deg, ${color}88, ${color})`,
          borderRadius: '3px',
          transition: 'width 0.8s cubic-bezier(0.34,1.56,0.64,1)'
        }} />
      </div>
    </div>
  )
}

function SignalCard({ sig, index }) {
  const typeRu = SIGNAL_TYPE_RU[sig.type] || sig.type
  const strRu  = SIGNAL_STR_RU[sig.strength] || sig.strength
  const strPct = sig.strength === 'strong' ? 90 : sig.strength === 'moderate' ? 60 : 30
  const isPositive = sig.type === 'momentum' || sig.type === 'breakout'

  return (
    <div style={{
      padding: '14px 16px',
      background: 'rgba(17,24,39,0.6)',
      borderRadius: '10px',
      border: `1px solid ${isPositive ? 'rgba(16,185,129,0.2)' : 'rgba(99,102,241,0.2)'}`,
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
      animation: `slideInUp 0.3s ease ${index * 0.06}s both`
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <span className={`badge badge-${isPositive ? 'bullish' : 'indigo'}`}>{typeRu}</span>
        <span className="badge badge-muted" style={{ fontSize: '11px' }}>{strRu}</span>
      </div>
      {sig.description && (
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: 0, lineHeight: '1.65' }}>
          {sig.description}
        </p>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style={{ flex: 1, height: '3px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: `${strPct}%`,
            background: isPositive ? 'rgba(16,185,129,0.7)' : 'rgba(99,102,241,0.7)',
            borderRadius: '2px', transition: 'width 0.6s ease'
          }} />
        </div>
        <span style={{ fontSize: '10px', color: 'var(--text-muted)', width: '28px', textAlign: 'right' }}>
          {strPct}%
        </span>
      </div>
    </div>
  )
}

function ForecastCard({ analysis }) {
  const dir      = analysis.forecast_direction || 'sideways'
  const dirRu    = FORECAST_DIR_RU[dir] || dir
  const dirColor = FORECAST_DIR_COLOR[dir] || 'var(--text-secondary)'
  const dirIcon  = FORECAST_DIR_ICON[dir] || '↔'
  const target   = analysis.forecast_price_target
  const period   = analysis.forecast_period
  const rationale = analysis.forecast_rationale

  return (
    <div style={{
      padding: '20px 24px',
      background: 'rgba(17,24,39,0.8)',
      borderRadius: '12px',
      border: `1px solid ${dirColor}33`,
      display: 'flex',
      flexDirection: 'column',
      gap: '16px',
      position: 'relative',
      overflow: 'hidden'
    }}>
      {/* glow accent */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: '2px',
        background: `linear-gradient(90deg, transparent, ${dirColor}, transparent)`
      }} />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '40px', height: '40px', borderRadius: '10px',
            background: `${dirColor}20`,
            border: `1px solid ${dirColor}40`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '20px', color: dirColor, fontWeight: '700'
          }}>
            {dirIcon}
          </div>
          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '3px' }}>
              Прогноз направления
            </div>
            <div style={{ fontSize: '18px', fontWeight: '700', color: dirColor }}>{dirRu}</div>
          </div>
        </div>

        {target != null && (
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '3px' }}>
              Целевая цена
            </div>
            <div style={{ fontSize: '22px', fontWeight: '700', color: dirColor, fontFamily: 'var(--font-mono)' }}>
              ${target.toFixed(2)}
            </div>
          </div>
        )}
      </div>

      {period && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Горизонт прогноза:
          </span>
          <span className="badge badge-muted" style={{ fontSize: '11px' }}>{period}</span>
        </div>
      )}

      {rationale && (
        <div style={{
          padding: '14px 16px',
          background: 'rgba(0,0,0,0.3)',
          borderRadius: '8px',
          borderLeft: `3px solid ${dirColor}60`,
          fontSize: '13px',
          color: 'var(--text-secondary)',
          lineHeight: '1.7',
          fontStyle: 'italic'
        }}>
          {rationale}
        </div>
      )}
    </div>
  )
}

function HistoryItem({ item, isActive, onClick }) {
  const sentiment = item.sentiment || item.gemini_sentiment || 'neutral'
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', flexDirection: 'column', gap: '5px',
        padding: '10px 14px', borderRadius: '10px',
        background: isActive ? 'rgba(99,102,241,0.12)' : 'rgba(17,24,39,0.5)',
        border: `1px solid ${isActive ? 'rgba(99,102,241,0.4)' : 'transparent'}`,
        cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s ease',
        fontFamily: 'inherit', width: '100%'
      }}
      onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'rgba(17,24,39,0.8)' }}
      onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'rgba(17,24,39,0.5)' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span className={`badge badge-${sentiment === 'bullish' ? 'bullish' : sentiment === 'bearish' ? 'bearish' : 'neutral'}`}
          style={{ fontSize: '10px', padding: '2px 7px' }}>
          {SENTIMENT_ICON[sentiment]} {SENTIMENT_LABEL[sentiment] || sentiment}
        </span>
        <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-primary)' }}>
          {item.ticker || item.ticker_symbol}
        </span>
      </div>
      {item.forecast_direction && (
        <span style={{ fontSize: '11px', color: FORECAST_DIR_COLOR[item.forecast_direction] || 'var(--text-muted)' }}>
          {FORECAST_DIR_ICON[item.forecast_direction]} {FORECAST_DIR_RU[item.forecast_direction]}
          {item.forecast_price_target ? ` → $${Number(item.forecast_price_target).toFixed(2)}` : ''}
        </span>
      )}
      <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
        {item.created_at
          ? formatDistanceToNow(new Date(item.created_at), { addSuffix: true, locale: ru })
          : ''}
      </span>
    </button>
  )
}

export default function AIAnalysisPanel() {
  const [ticker, setTicker] = useState('AAPL')
  const [period, setPeriod] = useState('3mo')
  const [interval, setInterval] = useState('1d')

  const [analysis, setAnalysis] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState(null)

  const loadHistory = useCallback(async (tickerVal) => {
    setHistoryLoading(true)
    try {
      const r = await analysisApi.getHistory(tickerVal || ticker, 10)
      const items = r.data || []
      setHistory(items)
      if (items.length && !analysis) {
        setAnalysis(items[0])
        setSelectedId(items[0].id)
      }
    } catch {
      // non-fatal
    } finally {
      setHistoryLoading(false)
    }
  }, [ticker, analysis])

  useEffect(() => { loadHistory() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleRunAnalysis = useCallback(async () => {
    if (!ticker.trim()) return
    setLoading(true)
    setError('')
    try {
      const r = await analysisApi.runAnalysis(ticker.trim().toUpperCase(), period, interval)
      setAnalysis(r.data)
      setSelectedId(r.data?.id)
      loadHistory(ticker.trim().toUpperCase())
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Ошибка анализа')
    } finally {
      setLoading(false)
    }
  }, [ticker, period, interval, loadHistory])

  const handleSelectHistory = useCallback(async (item) => {
    const id = item.id
    setSelectedId(id)
    if (id) {
      try {
        const r = await analysisApi.getById(id)
        setAnalysis(r.data)
      } catch {
        setAnalysis(item)
      }
    } else {
      setAnalysis(item)
    }
  }, [])

  // Normalize field names — API returns both gemini_* and short aliases
  const norm = analysis ? {
    ...analysis,
    summary:    analysis.summary    ?? analysis.gemini_summary,
    sentiment:  analysis.sentiment  ?? analysis.gemini_sentiment  ?? 'neutral',
    confidence: analysis.confidence ?? analysis.gemini_confidence ?? null,
    signals:    analysis.signals    ?? analysis.gemini_signals    ?? [],
    key_levels: analysis.key_levels ?? analysis.gemini_key_levels ?? [],
    risk_factors: analysis.risk_factors ?? analysis.gemini_risk_factors ?? [],
    ticker:     analysis.ticker     ?? analysis.ticker_symbol,
  } : null

  const confidence = norm?.confidence != null ? Math.round(norm.confidence * 100) : null
  const signals    = Array.isArray(norm?.signals) ? norm.signals : []
  const keyLevels  = Array.isArray(norm?.key_levels) ? norm.key_levels : []
  const riskFactors = Array.isArray(norm?.risk_factors) ? norm.risk_factors : []
  const isMock     = norm?.mock_mode || norm?.is_mock
  const hasForecast = norm?.forecast_direction || norm?.forecast_price_target || norm?.forecast_rationale

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', animation: 'slideInUp 0.35s ease' }}>

      {/* Controls */}
      <div className="glass-card" style={{ padding: '20px 24px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'flex-end' }}>
          <div className="form-group" style={{ flex: '1 1 140px' }}>
            <label className="input-label">Тикер</label>
            <input
              className="input-field"
              type="text"
              value={ticker}
              onChange={e => setTicker(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && handleRunAnalysis()}
              placeholder="AAPL"
              style={{ textTransform: 'uppercase' }}
            />
          </div>
          <div className="form-group" style={{ flex: '0 0 110px' }}>
            <label className="input-label">Период</label>
            <select className="select-field" value={period} onChange={e => setPeriod(e.target.value)}>
              {PERIODS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ flex: '0 0 110px' }}>
            <label className="input-label">Интервал</label>
            <select className="select-field" value={interval} onChange={e => setInterval(e.target.value)}>
              {INTERVALS.map(i => <option key={i} value={i}>{i}</option>)}
            </select>
          </div>
          <button
            className={`btn btn-primary${loading ? ' btn-loading' : ''}`}
            onClick={handleRunAnalysis}
            disabled={loading || !ticker.trim()}
          >
            {loading ? '' : '⚡ Запустить анализ'}
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => loadHistory(ticker)}
            disabled={historyLoading}
          >
            {historyLoading ? <span className="spinner spinner-sm" /> : '↺ История'}
          </button>
        </div>
        {error && (
          <div className="alert alert-error" style={{ marginTop: '12px' }}>
            <span>⚠</span> {error}
          </div>
        )}
      </div>

      <div className="analysis-grid">
        {/* Main analysis panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

          {/* Result card */}
          <div className="glass-card" style={{ padding: '24px' }}>
            {loading ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div className="skeleton skeleton-text-lg" style={{ width: '40%' }} />
                <div className="skeleton skeleton-text" style={{ width: '80%' }} />
                <div className="skeleton skeleton-text" style={{ width: '65%' }} />
                <div className="skeleton" style={{ height: '90px' }} />
                <div className="skeleton" style={{ height: '60px' }} />
              </div>
            ) : norm ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>

                {isMock && (
                  <div className="alert alert-warning">
                    <span>⚠</span>
                    <span>Демо-режим — результаты смоделированы, не от живого ИИ</span>
                  </div>
                )}

                {/* Header row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                  <div style={{
                    width: '44px', height: '44px', borderRadius: '12px',
                    background: norm.sentiment === 'bullish'
                      ? 'rgba(16,185,129,0.15)' : norm.sentiment === 'bearish'
                      ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)',
                    border: `1px solid ${norm.sentiment === 'bullish'
                      ? 'rgba(16,185,129,0.3)' : norm.sentiment === 'bearish'
                      ? 'rgba(239,68,68,0.3)' : 'rgba(245,158,11,0.3)'}`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '20px',
                    color: norm.sentiment === 'bullish' ? 'var(--success)' : norm.sentiment === 'bearish' ? 'var(--error)' : 'var(--warning)'
                  }}>
                    {SENTIMENT_ICON[norm.sentiment] || '►'}
                  </div>
                  <span className={`badge badge-${norm.sentiment === 'bullish' ? 'bullish' : norm.sentiment === 'bearish' ? 'bearish' : 'neutral'}`}
                    style={{ fontSize: '13px', padding: '5px 14px' }}>
                    {SENTIMENT_LABEL[norm.sentiment] || norm.sentiment}
                  </span>
                  <span className="badge badge-indigo">{norm.ticker}</span>
                  <span className="badge badge-muted" style={{ fontSize: '11px' }}>
                    {norm.period} / {norm.interval}
                  </span>
                  <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--text-muted)' }}>
                    {norm.created_at
                      ? formatDistanceToNow(new Date(norm.created_at), { addSuffix: true, locale: ru })
                      : ''}
                  </span>
                </div>

                {/* Confidence */}
                {confidence !== null && <ConfidenceBar pct={confidence} />}

                {/* Summary */}
                {norm.summary && (
                  <div>
                    <div className="section-title" style={{ marginBottom: '10px' }}>Анализ</div>
                    <div style={{
                      padding: '16px 18px',
                      background: 'rgba(99,102,241,0.06)',
                      borderRadius: '10px',
                      borderLeft: '3px solid var(--accent-primary)',
                      fontSize: '14px',
                      color: 'var(--text-secondary)',
                      lineHeight: '1.75',
                      fontStyle: 'italic'
                    }}>
                      {norm.summary}
                    </div>
                  </div>
                )}

                {/* Forecast */}
                {hasForecast && (
                  <div>
                    <div className="section-title" style={{ marginBottom: '12px' }}>Прогноз</div>
                    <ForecastCard analysis={norm} />
                  </div>
                )}

                {/* Signals */}
                {signals.length > 0 && (
                  <div>
                    <div className="section-title" style={{ marginBottom: '12px' }}>Торговые сигналы</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {signals.map((sig, idx) => <SignalCard key={idx} sig={sig} index={idx} />)}
                    </div>
                  </div>
                )}

                {/* Key Levels */}
                {keyLevels.length > 0 && (
                  <div>
                    <div className="section-title" style={{ marginBottom: '12px' }}>Ключевые уровни</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      {keyLevels.map((lvl, idx) => (
                        <span key={idx} style={{
                          padding: '5px 12px',
                          background: 'rgba(6,182,212,0.1)',
                          border: '1px solid rgba(6,182,212,0.3)',
                          borderRadius: '6px',
                          fontSize: '13px',
                          fontFamily: 'var(--font-mono)',
                          color: 'var(--accent-cyan)',
                          fontWeight: '600'
                        }}>
                          ${typeof lvl === 'number' ? lvl.toFixed(2) : lvl}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Risk Factors */}
                {riskFactors.length > 0 && (
                  <div>
                    <div className="section-title" style={{ marginBottom: '10px' }}>Факторы риска</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {riskFactors.map((risk, idx) => (
                        <div key={idx} style={{
                          display: 'flex', alignItems: 'flex-start', gap: '8px',
                          padding: '8px 12px',
                          background: 'rgba(239,68,68,0.06)',
                          border: '1px solid rgba(239,68,68,0.15)',
                          borderRadius: '8px',
                          fontSize: '13px',
                          color: '#fca5a5',
                          lineHeight: '1.5'
                        }}>
                          <span style={{ flexShrink: 0, marginTop: '1px' }}>⚠</span>
                          <span>{risk}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-state-icon">◈</div>
                <div className="empty-state-title">Нет данных анализа</div>
                <div className="empty-state-sub">
                  Выберите тикер, период и интервал, затем нажмите «Запустить анализ»
                </div>
              </div>
            )}
          </div>

          {/* Token visualizer */}
          {norm?.coarse_tokens?.length > 0 && <TokenizerVisual analysis={norm} />}
        </div>

        {/* History sidebar */}
        <div className="glass-card" style={{ padding: '16px', overflowY: 'auto', maxHeight: '80vh' }}>
          <div className="section-title" style={{ marginBottom: '14px' }}>История анализов</div>
          {historyLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {[1, 2, 3, 4].map(i => (
                <div key={i} className="skeleton" style={{ height: '68px', borderRadius: '10px' }} />
              ))}
            </div>
          ) : history.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {history.map((item, idx) => (
                <HistoryItem
                  key={idx}
                  item={item}
                  isActive={selectedId === item.id}
                  onClick={() => handleSelectHistory(item)}
                />
              ))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)', fontSize: '13px' }}>
              История пуста
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

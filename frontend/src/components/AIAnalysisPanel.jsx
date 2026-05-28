import { useState, useEffect, useCallback } from 'react'
import { analysisApi } from '../api/client.js'
import TokenizerVisual from './TokenizerVisual.jsx'
import { formatDistanceToNow } from 'date-fns'

const PERIODS = ['1d', '5d', '1mo', '3mo', '6mo', '1y']
const INTERVALS = ['1m', '5m', '15m', '1h', '1d']

function SentimentIcon({ sentiment }) {
  if (sentiment === 'bullish') return <span style={{ fontSize: '18px' }}>▲</span>
  if (sentiment === 'bearish') return <span style={{ fontSize: '18px' }}>▼</span>
  return <span style={{ fontSize: '18px' }}>►</span>
}

function SignalStrengthBar({ strength }) {
  const pct = typeof strength === 'number'
    ? Math.max(0, Math.min(1, strength)) * 100
    : strength === 'strong' ? 90 : strength === 'moderate' ? 60 : 30
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      <div style={{ flex: 1, height: '4px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: `${pct}%`,
          background: 'var(--accent-gradient)',
          borderRadius: '2px',
          transition: 'width 0.6s ease'
        }} />
      </div>
      <span style={{ fontSize: '11px', color: 'var(--text-muted)', width: '30px', textAlign: 'right' }}>
        {Math.round(pct)}%
      </span>
    </div>
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
        setSelectedId(items[0].id || items[0]._id)
      }
    } catch {
      // non-fatal: history list is informational
    } finally {
      setHistoryLoading(false)
    }
  }, [ticker, analysis])

  useEffect(() => {
    loadHistory()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleRunAnalysis = useCallback(async () => {
    if (!ticker.trim()) return
    setLoading(true)
    setError('')
    try {
      const r = await analysisApi.runAnalysis(ticker.trim().toUpperCase(), period, interval)
      setAnalysis(r.data)
      setSelectedId(r.data?.id || r.data?._id)
      loadHistory(ticker.trim().toUpperCase())
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }, [ticker, period, interval, loadHistory])

  const handleSelectHistory = useCallback(async (item) => {
    const id = item.id || item._id
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

  const sentiment = analysis?.sentiment || 'neutral'
  const confidence = analysis?.confidence != null ? Math.round(analysis.confidence * 100) : null
  const signals = Array.isArray(analysis?.signals) ? analysis.signals : []
  const keyLevels = analysis?.key_levels || {}
  const riskFactors = Array.isArray(analysis?.risk_factors) ? analysis.risk_factors : []
  const isMock = analysis?.mock_mode || analysis?.is_mock

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', animation: 'slideInUp 0.35s ease' }}>
      {/* Controls */}
      <div className="glass-card" style={{ padding: '20px 24px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'flex-end' }}>
          <div className="form-group" style={{ flex: '1 1 140px' }}>
            <label className="input-label">Ticker</label>
            <input
              className="input-field"
              type="text"
              value={ticker}
              onChange={e => setTicker(e.target.value.toUpperCase())}
              placeholder="AAPL"
              style={{ textTransform: 'uppercase' }}
            />
          </div>
          <div className="form-group" style={{ flex: '0 0 110px' }}>
            <label className="input-label">Period</label>
            <select className="select-field" value={period} onChange={e => setPeriod(e.target.value)}>
              {PERIODS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ flex: '0 0 110px' }}>
            <label className="input-label">Interval</label>
            <select className="select-field" value={interval} onChange={e => setInterval(e.target.value)}>
              {INTERVALS.map(i => <option key={i} value={i}>{i}</option>)}
            </select>
          </div>
          <button
            className={`btn btn-primary${loading ? ' btn-loading' : ''}`}
            onClick={handleRunAnalysis}
            disabled={loading || !ticker.trim()}
            style={{ paddingBottom: '1px' }}
          >
            {loading ? '' : '⚡ Run New Analysis'}
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => loadHistory(ticker)}
            disabled={historyLoading}
          >
            {historyLoading ? <span className="spinner spinner-sm" /> : '↺ History'}
          </button>
        </div>
        {error && (
          <div className="alert alert-error" style={{ marginTop: '12px' }}>
            <span>⚠</span> {error}
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 280px', gap: '16px' }}>
        {/* Main analysis */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Result card */}
          <div className="glass-card" style={{ padding: '24px' }}>
            {loading ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div className="skeleton skeleton-text-lg" style={{ width: '40%' }} />
                <div className="skeleton skeleton-text" style={{ width: '80%' }} />
                <div className="skeleton skeleton-text" style={{ width: '60%' }} />
                <div className="skeleton" style={{ height: '80px' }} />
              </div>
            ) : analysis ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {isMock && (
                  <div className="mock-banner">
                    <span>⚠</span>
                    <span>Mock mode — results are simulated, not from live AI</span>
                  </div>
                )}

                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                  <SentimentIcon sentiment={sentiment} />
                  <span className={`badge badge-${sentiment === 'bullish' ? 'bullish' : sentiment === 'bearish' ? 'bearish' : 'neutral'}`} style={{ fontSize: '13px', padding: '5px 14px' }}>
                    {sentiment.toUpperCase()}
                  </span>
                  <span className="badge badge-indigo">{analysis.ticker}</span>
                  <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--text-muted)' }}>
                    {analysis.created_at
                      ? formatDistanceToNow(new Date(analysis.created_at), { addSuffix: true })
                      : ''}
                  </span>
                </div>

                {/* Confidence */}
                {confidence !== null && (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>AI Confidence</span>
                      <span style={{ fontSize: '14px', fontWeight: '700', color: 'var(--accent-cyan)' }}>{confidence}%</span>
                    </div>
                    <div className="confidence-bar-track">
                      <div className="confidence-bar-fill" style={{ width: `${confidence}%` }} />
                    </div>
                  </div>
                )}

                {/* Summary */}
                {analysis.summary && (
                  <div>
                    <div className="section-title" style={{ marginBottom: '10px' }}>Summary</div>
                    <div className="quote-block">{analysis.summary}</div>
                  </div>
                )}

                {/* Signals */}
                {signals.length > 0 && (
                  <div>
                    <div className="section-title" style={{ marginBottom: '12px' }}>Trading Signals</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      {signals.map((sig, idx) => (
                        <div key={idx} style={{
                          padding: '12px 16px',
                          background: 'rgba(17,24,39,0.5)',
                          borderRadius: '10px',
                          border: '1px solid var(--glass-border)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '8px',
                          animation: `token-appear 0.3s ease ${idx * 0.05}s both`
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span className={`badge badge-${sig.type === 'buy' ? 'bullish' : sig.type === 'sell' ? 'bearish' : 'neutral'}`}>
                              {sig.type || 'signal'}
                            </span>
                            {sig.strength && (
                              <span className="badge badge-muted" style={{ fontSize: '11px' }}>{sig.strength}</span>
                            )}
                          </div>
                          {sig.description && (
                            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: 0, lineHeight: '1.6' }}>
                              {sig.description}
                            </p>
                          )}
                          {sig.strength != null && <SignalStrengthBar strength={sig.strength} />}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Key Levels */}
                {Object.keys(keyLevels).length > 0 && (
                  <div>
                    <div className="section-title" style={{ marginBottom: '12px' }}>Key Price Levels</div>
                    <div>
                      {Object.entries(keyLevels).map(([label, price], idx) => (
                        <div key={idx} className="key-level-bar">
                          <span className="key-level-label">{label}</span>
                          <span className="key-level-price">
                            {typeof price === 'number' ? `$${price.toFixed(2)}` : String(price)}
                          </span>
                          <div style={{ flex: 1, height: '3px', background: 'var(--bg-tertiary)', borderRadius: '2px' }}>
                            <div style={{
                              height: '100%',
                              width: label.toLowerCase().includes('support') ? '35%' : label.toLowerCase().includes('resist') ? '75%' : '55%',
                              background: label.toLowerCase().includes('support')
                                ? 'rgba(16,185,129,0.6)'
                                : label.toLowerCase().includes('resist')
                                ? 'rgba(239,68,68,0.6)'
                                : 'rgba(99,102,241,0.6)',
                              borderRadius: '2px'
                            }} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Risk Factors */}
                {riskFactors.length > 0 && (
                  <div>
                    <div className="section-title" style={{ marginBottom: '10px' }}>Risk Factors</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      {riskFactors.map((risk, idx) => (
                        <span key={idx} className="risk-chip">⚠ {risk}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-state-icon">◈</div>
                <div className="empty-state-title">No analysis results</div>
                <div className="empty-state-sub">
                  Select a ticker, choose period and interval, then run the analysis
                </div>
              </div>
            )}
          </div>

          {/* Token visualizer */}
          {analysis?.coarse_tokens?.length > 0 && <TokenizerVisual analysis={analysis} />}
        </div>

        {/* History sidebar */}
        <div className="glass-card" style={{ padding: '16px', overflowY: 'auto', maxHeight: '80vh' }}>
          <div className="section-title" style={{ marginBottom: '12px' }}>History</div>
          {historyLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {[1, 2, 3, 4].map(i => (
                <div key={i} className="skeleton" style={{ height: '64px', borderRadius: '8px' }} />
              ))}
            </div>
          ) : history.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {history.map((item, idx) => {
                const id = item.id || item._id
                const isActive = selectedId === id
                return (
                  <button
                    key={idx}
                    onClick={() => handleSelectHistory(item)}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                      padding: '10px 12px',
                      borderRadius: '8px',
                      background: isActive ? 'rgba(99,102,241,0.15)' : 'rgba(17,24,39,0.5)',
                      border: `1px solid ${isActive ? 'rgba(99,102,241,0.4)' : 'transparent'}`,
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'all 0.15s ease',
                      fontFamily: 'inherit'
                    }}
                    onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'rgba(17,24,39,0.8)' }}
                    onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'rgba(17,24,39,0.5)' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span className={`badge badge-${item.sentiment === 'bullish' ? 'bullish' : item.sentiment === 'bearish' ? 'bearish' : 'neutral'}`} style={{ fontSize: '10px', padding: '2px 6px' }}>
                        {item.sentiment}
                      </span>
                      <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-primary)' }}>
                        {item.ticker}
                      </span>
                    </div>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {item.created_at
                        ? formatDistanceToNow(new Date(item.created_at), { addSuffix: true })
                        : ''}
                    </span>
                  </button>
                )
              })}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)', fontSize: '13px' }}>
              No history yet
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

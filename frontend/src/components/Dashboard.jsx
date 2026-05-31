import { useState, useEffect, useCallback } from 'react'
import { marketApi, analysisApi, newsApi } from '../api/client.js'
import CandleChart from './CandleChart.jsx'
import TokenizerVisual from './TokenizerVisual.jsx'
import { formatDistanceToNow } from 'date-fns'

const PERIODS = ['1d', '5d', '1mo', '3mo', '6mo', '1y']
const INTERVALS = ['1m', '5m', '15m', '1h', '1d']

function StatCard({ label, value, sub, accentColor }) {
  return (
    <div className="glass-card stat-card" style={{
      borderTop: `2px solid ${accentColor || 'var(--accent-primary)'}`,
      animation: 'slideInUp 0.35s ease'
    }}>
      <div className="stat-card-label">{label}</div>
      <div className="stat-card-value" style={{ color: accentColor || 'var(--text-primary)' }}>
        {value ?? <span className="skeleton skeleton-text-lg" style={{ width: '60px', display: 'inline-block' }} />}
      </div>
      {sub && <div className="stat-card-sub">{sub}</div>}
    </div>
  )
}

export default function Dashboard() {
  const [ticker, setTicker] = useState('AAPL')
  const [period, setPeriod] = useState('3mo')
  const [interval, setInterval] = useState('1d')
  const [forecastHorizon, setForecastHorizon] = useState('3 месяца')

  const FORECAST_HORIZONS = ['1 неделя', '1 месяц', '3 месяца', '6 месяцев', '1 год']

  const [tickers, setTickers] = useState([])
  const [candles, setCandles] = useState([])
  const [candlesLoading, setCandlesLoading] = useState(false)
  const [candlesError, setCandlesError] = useState('')

  const [analysis, setAnalysis] = useState(null)
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState('')

  const [latestNews, setLatestNews] = useState([])
  const [newsLoading, setNewsLoading] = useState(false)

  const [fetchLoading, setFetchLoading] = useState(false)
  const [fetchError, setFetchError] = useState('')
  const [fetchSuccess, setFetchSuccess] = useState('')

  // Load tickers list and latest analysis on mount
  useEffect(() => {
    marketApi.getTickers()
      .then(r => setTickers(r.data || []))
      .catch(() => {})

    newsApi.getLatest(5)
      .then(r => setLatestNews(r.data || []))
      .catch(() => {})

    analysisApi.getHistory('', 1)
      .then(r => {
        if (r.data?.length) setAnalysis(r.data[0])
      })
      .catch(() => {})
  }, [])

  const handleFetchData = useCallback(async () => {
    if (!ticker.trim()) return
    setFetchLoading(true)
    setFetchError('')
    setFetchSuccess('')
    setCandlesError('')
    try {
      await marketApi.fetchData(ticker.trim().toUpperCase(), period, interval)
      setFetchSuccess(`Data fetched for ${ticker.toUpperCase()}`)
      // Load candles immediately after fetch
      setCandlesLoading(true)
      const r = await marketApi.getCandles(ticker.trim().toUpperCase(), interval, 300)
      setCandles(r.data || [])
    } catch (err) {
      setFetchError(err.response?.data?.detail || err.message || 'Ошибка загрузки рыночных данных')
    } finally {
      setFetchLoading(false)
      setCandlesLoading(false)
    }
  }, [ticker, period, interval])

  const handleRunAnalysis = useCallback(async () => {
    if (!ticker.trim()) return
    setAnalysisLoading(true)
    setAnalysisError('')
    try {
      const r = await analysisApi.runAnalysis(ticker.trim().toUpperCase(), period, interval, forecastHorizon)
      setAnalysis(r.data)
    } catch (err) {
      setAnalysisError(err.response?.data?.detail || err.message || 'Ошибка выполнения анализа')
    } finally {
      setAnalysisLoading(false)
    }
  }, [ticker, period, interval, forecastHorizon])

  const loadCandles = useCallback(async () => {
    if (!ticker.trim()) return
    setCandlesLoading(true)
    setCandlesError('')
    try {
      const r = await marketApi.getCandles(ticker.trim().toUpperCase(), interval, 300)
      setCandles(r.data || [])
    } catch (err) {
      setCandlesError(err.response?.data?.detail || err.message || 'Ошибка загрузки свечей')
    } finally {
      setCandlesLoading(false)
    }
  }, [ticker, interval])

  // Stat card computations
  const lastAnalysisTime = analysis?.created_at
    ? formatDistanceToNow(new Date(analysis.created_at), { addSuffix: true })
    : '—'
  const confidence = analysis?.confidence != null
    ? `${Math.round(analysis.confidence * 100)}%`
    : '—'

  return (
    <div>
      {/* Stat cards */}
      <div className="stats-grid">
        <StatCard
          label="Активные тикеры"
          value={tickers.length || '0'}
          sub="Отслеживаемые инструменты"
          accentColor="var(--accent-primary)"
        />
        <StatCard
          label="Последний анализ"
          value={lastAnalysisTime}
          sub={analysis?.ticker || '—'}
          accentColor="var(--accent-cyan)"
        />
        <StatCard
          label="Точки данных"
          value={candles.length > 0 ? candles.length.toLocaleString() : '0'}
          sub={`${ticker.toUpperCase()} · ${interval}`}
          accentColor="var(--accent-secondary)"
        />
        <StatCard
          label="Уверенность модели"
          value={confidence}
          sub={analysis?.sentiment || '—'}
          accentColor="var(--success)"
        />
      </div>

      {/* Ticker / params row */}
      <div className="glass-card" style={{ padding: '20px 24px', marginBottom: '16px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'flex-end' }}>
          <div className="form-group" style={{ flex: '1 1 160px', minWidth: '120px' }}>
            <label className="input-label">Тикер</label>
            <input
              className="input-field"
              type="text"
              placeholder="напр. AAPL, TSLA"
              value={ticker}
              onChange={e => setTicker(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && handleFetchData()}
              style={{ textTransform: 'uppercase' }}
            />
          </div>

          <div className="form-group" style={{ flex: '0 0 120px' }}>
            <label className="input-label">История</label>
            <select
              className="select-field"
              value={period}
              onChange={e => setPeriod(e.target.value)}
            >
              {PERIODS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>

          <div className="form-group" style={{ flex: '0 0 120px' }}>
            <label className="input-label">Таймфрейм</label>
            <select
              className="select-field"
              value={interval}
              onChange={e => setInterval(e.target.value)}
            >
              {INTERVALS.map(i => <option key={i} value={i}>{i}</option>)}
            </select>
          </div>

          <div className="form-group" style={{ flex: '0 0 140px' }}>
            <label className="input-label" style={{ color: 'var(--accent-cyan)' }}>Горизонт прогноза</label>
            <select
              className="select-field"
              value={forecastHorizon}
              onChange={e => setForecastHorizon(e.target.value)}
              style={{ borderColor: 'var(--accent-cyan)' }}
            >
              {FORECAST_HORIZONS.map(h => <option key={h} value={h}>{h}</option>)}
            </select>
          </div>

          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', paddingBottom: '1px' }}>
            <button
              className={`btn btn-secondary${fetchLoading ? ' btn-loading' : ''}`}
              onClick={handleFetchData}
              disabled={fetchLoading || !ticker.trim()}
            >
              {fetchLoading ? '' : '↓ Загрузить данные'}
            </button>
            <button
              className={`btn btn-primary${analysisLoading ? ' btn-loading' : ''}`}
              onClick={handleRunAnalysis}
              disabled={analysisLoading || !ticker.trim()}
            >
              {analysisLoading ? '' : '⚡ Запустить анализ'}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={loadCandles}
              disabled={candlesLoading || !ticker.trim()}
              title="Перезагрузить график"
            >
              ↺ График
            </button>
          </div>
        </div>

        {/* Status messages */}
        {fetchError && (
          <div className="alert alert-error" style={{ marginTop: '12px' }}>
            <span>⚠</span> {fetchError}
          </div>
        )}
        {fetchSuccess && (
          <div className="alert alert-success" style={{ marginTop: '12px' }}>
            <span>✓</span> {fetchSuccess}
          </div>
        )}
        {analysisError && (
          <div className="alert alert-error" style={{ marginTop: '12px' }}>
            <span>⚠</span> {analysisError}
          </div>
        )}
        {candlesError && (
          <div className="alert alert-warning" style={{ marginTop: '12px' }}>
            <span>⚠</span> {candlesError}
          </div>
        )}
      </div>

      {/* Chart */}
      <div className="glass-card" style={{ padding: '20px 24px', marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <h2 className="section-title">
            {ticker.toUpperCase()} Свечной график
          </h2>
          {candles.length > 0 && (
            <span className="badge badge-muted">{candles.length} свечей</span>
          )}
        </div>
        <CandleChart candles={candles} loading={candlesLoading} ticker={ticker} analysis={analysis} />
      </div>

      {/* Token visualizer if analysis has tokens */}
      {analysis?.coarse_tokens?.length > 0 && (
        <div style={{ marginBottom: '16px' }}>
          <TokenizerVisual analysis={analysis} />
        </div>
      )}

      {/* Bottom row */}
      <div className="dashboard-grid">
        {/* Latest analysis summary */}
        <div className="glass-card" style={{ padding: '20px 24px' }}>
          <h2 className="section-title" style={{ marginBottom: '16px' }}>Квантитативная аналитика</h2>
          {analysisLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {[80, 60, 90, 50].map((w, i) => (
                <div key={i} className="skeleton skeleton-text" style={{ width: `${w}%` }} />
              ))}
            </div>
          ) : analysis ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                <span className={`badge badge-${analysis.sentiment === 'bullish' ? 'bullish' : analysis.sentiment === 'bearish' ? 'bearish' : 'neutral'}`}>
                  {analysis.sentiment === 'bullish' ? '▲' : analysis.sentiment === 'bearish' ? '▼' : '►'} {analysis.sentiment}
                </span>
                <span className="badge badge-indigo">{analysis.ticker}</span>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                  {lastAnalysisTime}
                </span>
              </div>
              {analysis.confidence != null && (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Уверенность</span>
                    <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--accent-cyan)' }}>{confidence}</span>
                  </div>
                  <div className="confidence-bar-track">
                    <div className="confidence-bar-fill" style={{ width: confidence }} />
                  </div>
                </div>
              )}
              {analysis.summary && (
                <div className="quote-block">{analysis.summary}</div>
              )}
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">◈</div>
              <div className="empty-state-title">Нет данных анализа</div>
              <div className="empty-state-sub">Укажите тикер и нажмите «Запустить анализ»</div>
            </div>
          )}
        </div>

        {/* Latest news */}
        <div className="glass-card" style={{ padding: '20px 24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h2 className="section-title">Сводка новостей</h2>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setNewsLoading(true)
                newsApi.getLatest(5)
                  .then(r => setLatestNews(r.data || []))
                  .catch(() => {})
                  .finally(() => setNewsLoading(false))
              }}
              disabled={newsLoading}
            >
              {newsLoading ? <span className="spinner spinner-sm" /> : '↺'}
            </button>
          </div>
          {newsLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {[1, 2, 3].map(i => (
                <div key={i} className="skeleton skeleton-card" style={{ height: '72px' }} />
              ))}
            </div>
          ) : latestNews.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {latestNews.map((item, idx) => (
                <a
                  key={idx}
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="news-card"
                  style={{ textDecoration: 'none' }}
                >
                  <div className="news-card-meta">
                    {item.source && <span className="news-source-badge">{item.source}</span>}
                    {item.ticker && <span className="badge badge-cyan" style={{ fontSize: '10px' }}>{item.ticker}</span>}
                    {item.published_at && (
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                        {formatDistanceToNow(new Date(item.published_at), { addSuffix: true })}
                      </span>
                    )}
                  </div>
                  <div className="news-card-title">{item.title}</div>
                </a>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">◎</div>
              <div className="empty-state-title">Новости не загружены</div>
              <div className="empty-state-sub">Ожидание рыночного фона...</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

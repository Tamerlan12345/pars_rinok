import { useState, useEffect, useCallback, useRef } from 'react'
import { newsApi } from '../api/client.js'
import { formatDistanceToNow, format } from 'date-fns'

const AUTO_REFRESH_MS = 5 * 60 * 1000 // 5 minutes

function NewsCardSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {[1, 2, 3, 4, 5].map(i => (
        <div key={i} style={{
          padding: '16px 20px',
          borderRadius: '12px',
          background: 'rgba(17,24,39,0.6)',
          border: '1px solid var(--glass-border)',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px'
        }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <div className="skeleton" style={{ width: '60px', height: '18px', borderRadius: '4px' }} />
            <div className="skeleton" style={{ width: '40px', height: '18px', borderRadius: '4px' }} />
            <div className="skeleton" style={{ width: '70px', height: '18px', borderRadius: '4px', marginLeft: 'auto' }} />
          </div>
          <div className="skeleton skeleton-text" style={{ width: '95%' }} />
          <div className="skeleton skeleton-text" style={{ width: '70%' }} />
        </div>
      ))}
    </div>
  )
}

function NewsCard({ item }) {
  return (
    <a
      href={item.url || '#'}
      target="_blank"
      rel="noopener noreferrer"
      className="news-card"
      style={{ textDecoration: 'none', animation: 'slideInUp 0.25s ease' }}
    >
      <div className="news-card-meta">
        {item.source && <span className="news-source-badge">{item.source}</span>}
        {item.ticker && (
          <span className="badge badge-cyan" style={{ fontSize: '10px', padding: '2px 6px' }}>
            {item.ticker}
          </span>
        )}
        {item.published_at && (
          <span
            title={format(new Date(item.published_at), 'PPPp')}
            style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: 'auto' }}
          >
            {formatDistanceToNow(new Date(item.published_at), { addSuffix: true })}
          </span>
        )}
      </div>
      <div className="news-card-title">{item.title}</div>
      {item.summary && (
        <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0, lineHeight: '1.5' }}>
          {item.summary.length > 160 ? item.summary.slice(0, 157) + '…' : item.summary}
        </p>
      )}
    </a>
  )
}

const KNOWN_TICKERS = ['AAPL', 'TSLA', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA']

export default function NewsPanel() {
  const [news, setNews] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [lastUpdated, setLastUpdated] = useState(null)
  const [filterTicker, setFilterTicker] = useState('ALL')
  const [limit, setLimit] = useState(30)
  const [fetchTicker, setFetchTicker] = useState('')
  const [fetching, setFetching] = useState(false)
  const timerRef = useRef(null)

  const loadNews = useCallback(async (tickerFilter, lim) => {
    setLoading(true)
    setError('')
    try {
      let r
      if (tickerFilter && tickerFilter !== 'ALL') {
        r = await newsApi.getByTicker(tickerFilter, lim || limit)
      } else {
        r = await newsApi.getLatest(lim || limit)
      }
      setNews(r.data || [])
      setLastUpdated(new Date())
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load news')
    } finally {
      setLoading(false)
    }
  }, [limit])

  // Initial load + auto-refresh
  useEffect(() => {
    loadNews(filterTicker)
    timerRef.current = setInterval(() => loadNews(filterTicker), AUTO_REFRESH_MS)
    return () => clearInterval(timerRef.current)
  }, [filterTicker, loadNews])

  const handleFetchNews = useCallback(async () => {
    if (!fetchTicker.trim()) return
    setFetching(true)
    setError('')
    try {
      await newsApi.fetchNews(fetchTicker.trim().toUpperCase())
      await loadNews(filterTicker)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to fetch news')
    } finally {
      setFetching(false)
    }
  }, [fetchTicker, filterTicker, loadNews])

  const handleFilterChange = useCallback((t) => {
    setFilterTicker(t)
    loadNews(t)
  }, [loadNews])

  // Extract unique tickers from loaded news for dynamic pills
  const availableTickers = ['ALL', ...Array.from(
    new Set([
      ...KNOWN_TICKERS,
      ...news.map(n => n.ticker).filter(Boolean)
    ])
  )]

  const displayedNews = news

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', animation: 'slideInUp 0.35s ease' }}>
      {/* Header controls */}
      <div className="glass-card" style={{ padding: '20px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <h2 className="section-title">Market News</h2>
            <span className="badge badge-muted">{displayedNews.length}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            {lastUpdated && (
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Updated {formatDistanceToNow(lastUpdated, { addSuffix: true })}
              </span>
            )}
            <select
              className="select-field"
              style={{ width: '100px' }}
              value={limit}
              onChange={e => {
                setLimit(Number(e.target.value))
                loadNews(filterTicker, Number(e.target.value))
              }}
            >
              {[20, 50, 100].map(n => <option key={n} value={n}>{n} items</option>)}
            </select>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => loadNews(filterTicker)}
              disabled={loading}
            >
              {loading ? <span className="spinner spinner-sm" /> : '↺ Refresh'}
            </button>
          </div>
        </div>

        {/* Fetch new news row */}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="form-group" style={{ flex: '1 1 160px' }}>
            <label className="input-label">Fetch news for ticker</label>
            <input
              className="input-field"
              type="text"
              placeholder="e.g. TSLA"
              value={fetchTicker}
              onChange={e => setFetchTicker(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && handleFetchNews()}
              style={{ textTransform: 'uppercase' }}
            />
          </div>
          <button
            className={`btn btn-cyan${fetching ? ' btn-loading' : ''}`}
            onClick={handleFetchNews}
            disabled={fetching || !fetchTicker.trim()}
          >
            {fetching ? '' : '↓ Fetch News'}
          </button>
        </div>

        {error && (
          <div className="alert alert-error" style={{ marginTop: '12px' }}>
            <span>⚠</span> {error}
          </div>
        )}
      </div>

      {/* Ticker filter pills */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
        {availableTickers.slice(0, 12).map(t => (
          <button
            key={t}
            className={`btn btn-sm ${filterTicker === t ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => handleFilterChange(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {/* News list */}
      {loading ? (
        <NewsCardSkeleton />
      ) : displayedNews.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {displayedNews.map((item, idx) => (
            <NewsCard key={item.id || item._id || idx} item={item} />
          ))}
        </div>
      ) : (
        <div className="glass-card">
          <div className="empty-state">
            <div className="empty-state-icon">◎</div>
            <div className="empty-state-title">No news found</div>
            <div className="empty-state-sub">
              {filterTicker !== 'ALL'
                ? `No news for ${filterTicker}. Try fetching it above.`
                : 'Enter a ticker and fetch news from the controls above'}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

import { useState, useEffect, useCallback, useRef } from 'react'
import { logsApi } from '../api/client.js'
import { format } from 'date-fns'

const LEVEL_FILTERS = ['ALL', 'INFO', 'WARNING', 'ERROR', 'DEBUG']
const LEVEL_STYLES = {
  INFO:    { color: 'var(--accent-cyan)',  bg: 'rgba(6,182,212,0.12)',  border: 'rgba(6,182,212,0.3)' },
  WARNING: { color: 'var(--warning)',      bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.3)' },
  ERROR:   { color: 'var(--error)',        bg: 'rgba(239,68,68,0.12)',  border: 'rgba(239,68,68,0.3)' },
  DEBUG:   { color: 'var(--text-muted)',   bg: 'rgba(75,85,99,0.15)',   border: 'rgba(75,85,99,0.3)' }
}
const LIMIT_OPTIONS = [50, 100, 200]

function LevelBadge({ level }) {
  const s = LEVEL_STYLES[level?.toUpperCase()] || LEVEL_STYLES.DEBUG
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: '4px',
      fontSize: '10px',
      fontWeight: '700',
      letterSpacing: '0.06em',
      textTransform: 'uppercase',
      color: s.color,
      background: s.bg,
      border: `1px solid ${s.border}`,
      whiteSpace: 'nowrap'
    }}>
      {level || 'DEBUG'}
    </span>
  )
}

function ContextCell({ context }) {
  const [open, setOpen] = useState(false)
  if (!context || Object.keys(context).length === 0) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  return (
    <span>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          fontSize: '11px',
          color: 'var(--accent-primary)',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '0',
          fontFamily: 'inherit'
        }}
      >
        {open ? '▲ hide' : '▼ json'}
      </button>
      {open && (
        <pre style={{
          marginTop: '6px',
          padding: '8px 10px',
          background: 'var(--bg-primary)',
          borderRadius: '6px',
          fontSize: '11px',
          fontFamily: 'var(--font-mono)',
          color: 'var(--accent-cyan)',
          maxWidth: '400px',
          overflowX: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all'
        }}>
          {JSON.stringify(context, null, 2)}
        </pre>
      )}
    </span>
  )
}

export default function LogsPanel() {
  const [logs, setLogs] = useState([])
  const [displayed, setDisplayed] = useState([])
  const [levelFilter, setLevelFilter] = useState('ALL')
  const [limit, setLimit] = useState(100)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [sseConnected, setSseConnected] = useState(false)
  const tableBodyRef = useRef(null)
  const sseRef = useRef(null)

  const loadLogs = useCallback(async (lim) => {
    setLoading(true)
    setError('')
    try {
      const r = await logsApi.getRecent(lim || limit)
      const data = Array.isArray(r.data) ? r.data : (r.data?.logs || [])
      setLogs(data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load logs')
    } finally {
      setLoading(false)
    }
  }, [limit])

  useEffect(() => { loadLogs() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Filter displayed logs when raw logs or filter changes
  useEffect(() => {
    if (levelFilter === 'ALL') {
      setDisplayed(logs)
    } else {
      setDisplayed(logs.filter(l => (l.level || '').toUpperCase() === levelFilter))
    }
  }, [logs, levelFilter])

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScroll && tableBodyRef.current) {
      tableBodyRef.current.scrollTop = tableBodyRef.current.scrollHeight
    }
  }, [displayed, autoScroll])

  // Optional SSE connection (connect if endpoint exists)
  useEffect(() => {
    const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
    const token = localStorage.getItem('auth_token')
    let es
    try {
      es = new EventSource(`${BASE}/api/logs/stream?token=${token || ''}`)
      sseRef.current = es

      es.onopen = () => setSseConnected(true)

      es.onmessage = (ev) => {
        try {
          const entry = JSON.parse(ev.data)
          setLogs(prev => {
            // keep at most `limit` entries to avoid unbounded memory growth
            const next = [...prev, entry]
            return next.length > limit ? next.slice(next.length - limit) : next
          })
        } catch {
          // non-JSON SSE frames — ignore silently
        }
      }

      es.onerror = () => {
        setSseConnected(false)
        // don't reconnect in a tight loop — browser backs off automatically
      }
    } catch {
      // EventSource not available or URL invalid — degrade gracefully
    }

    return () => {
      es?.close()
      setSseConnected(false)
    }
  }, [limit])

  const handleClearDisplay = () => setLogs([])

  const levelCounts = LEVEL_FILTERS.slice(1).reduce((acc, lv) => {
    acc[lv] = logs.filter(l => (l.level || '').toUpperCase() === lv).length
    return acc
  }, {})

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', animation: 'slideInUp 0.35s ease' }}>
      {/* Toolbar */}
      <div className="glass-card" style={{ padding: '16px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <h2 className="section-title">System Logs</h2>

          {/* SSE indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span className={`status-dot ${sseConnected ? 'online' : 'offline'}`} />
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {sseConnected ? 'Live' : 'Polling'}
            </span>
          </div>

          <div style={{ flex: 1 }} />

          {/* Level filter buttons */}
          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
            {LEVEL_FILTERS.map(lv => (
              <button
                key={lv}
                className={`btn btn-sm ${levelFilter === lv ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setLevelFilter(lv)}
                title={lv === 'ALL' ? 'Show all levels' : `Show ${lv} only (${levelCounts[lv] || 0})`}
              >
                {lv}
                {lv !== 'ALL' && levelCounts[lv] > 0 && (
                  <span style={{
                    marginLeft: '4px',
                    fontSize: '10px',
                    fontWeight: '700',
                    color: LEVEL_STYLES[lv]?.color || 'currentColor'
                  }}>
                    {levelCounts[lv]}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Limit */}
          <select
            className="select-field"
            style={{ width: '100px' }}
            value={limit}
            onChange={e => {
              setLimit(Number(e.target.value))
              loadLogs(Number(e.target.value))
            }}
          >
            {LIMIT_OPTIONS.map(n => <option key={n} value={n}>{n} lines</option>)}
          </select>

          {/* Auto-scroll toggle */}
          <button
            className={`btn btn-sm ${autoScroll ? 'btn-secondary' : 'btn-ghost'}`}
            onClick={() => setAutoScroll(v => !v)}
            title="Toggle auto-scroll to bottom"
          >
            {autoScroll ? '⬇ Auto-scroll ON' : '⬇ Auto-scroll OFF'}
          </button>

          {/* Refresh */}
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => loadLogs()}
            disabled={loading}
          >
            {loading ? <span className="spinner spinner-sm" /> : '↺ Refresh'}
          </button>

          {/* Clear */}
          <button className="btn btn-danger btn-sm" onClick={handleClearDisplay}>
            ✕ Clear
          </button>
        </div>

        {error && (
          <div className="alert alert-error" style={{ marginTop: '10px' }}>
            <span>⚠</span> {error}
          </div>
        )}
      </div>

      {/* Log table */}
      <div className="glass-card" style={{ overflow: 'hidden' }}>
        {loading && displayed.length === 0 ? (
          <div className="loading-overlay">
            <span className="spinner" />
            <span>Loading logs…</span>
          </div>
        ) : displayed.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">▤</div>
            <div className="empty-state-title">No log entries</div>
            <div className="empty-state-sub">
              {levelFilter !== 'ALL'
                ? `No ${levelFilter} entries in the current batch`
                : 'No logs yet — refresh or wait for activity'}
            </div>
          </div>
        ) : (
          <div
            ref={tableBodyRef}
            style={{
              maxHeight: 'calc(100vh - 280px)',
              overflowY: 'auto',
              overflowX: 'auto'
            }}
          >
            <table className="data-table" style={{ minWidth: '800px' }}>
              <thead>
                <tr>
                  <th style={{ width: '180px' }}>Timestamp</th>
                  <th style={{ width: '90px' }}>Level</th>
                  <th style={{ width: '160px' }}>Event</th>
                  <th>Message</th>
                  <th style={{ width: '120px' }}>Context</th>
                </tr>
              </thead>
              <tbody>
                {displayed.map((entry, idx) => {
                  const level = (entry.level || 'DEBUG').toUpperCase()
                  const ts = entry.timestamp || entry.created_at || entry.time
                  const formattedTs = ts
                    ? (() => { try { return format(new Date(ts), 'yyyy-MM-dd HH:mm:ss') } catch { return String(ts) } })()
                    : '—'

                  return (
                    <tr key={entry.id || idx}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                        {formattedTs}
                      </td>
                      <td>
                        <LevelBadge level={level} />
                      </td>
                      <td style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                        {entry.event || entry.action || '—'}
                      </td>
                      <td style={{ fontSize: '13px', lineHeight: '1.5' }}>
                        {entry.message || entry.msg || '—'}
                      </td>
                      <td>
                        <ContextCell context={entry.context || entry.extra || entry.metadata} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Stats footer */}
      {displayed.length > 0 && (
        <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
          <span>Showing <strong style={{ color: 'var(--text-secondary)' }}>{displayed.length}</strong> of {logs.length} entries</span>
          {Object.entries(levelCounts).filter(([, c]) => c > 0).map(([lv, c]) => (
            <span key={lv} style={{ color: LEVEL_STYLES[lv]?.color }}>
              {lv}: {c}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

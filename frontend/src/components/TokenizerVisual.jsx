import { useState } from 'react'

// Token value → background color
function tokenColor(value) {
  if (value <= 7)  return '#0f2240'   // dark blue
  if (value <= 15) return '#1e40af'   // blue
  if (value <= 23) return '#6d28d9'   // violet
  return '#06b6d4'                    // bright cyan
}

// Fine token (0-7) → opacity
function fineOpacity(value) {
  return 0.2 + (value / 7) * 0.8
}

// Shannon entropy estimate over token array
function estimateEntropy(tokens) {
  if (!tokens.length) return 0
  const freq = {}
  for (const t of tokens) freq[t] = (freq[t] || 0) + 1
  let h = 0
  for (const count of Object.values(freq)) {
    const p = count / tokens.length
    h -= p * Math.log2(p)
  }
  return h.toFixed(3)
}

function TokenCell({ value, size, isCoarse, index }) {
  const [showTooltip, setShowTooltip] = useState(false)
  const bg = isCoarse ? tokenColor(value) : `rgba(99, 102, 241, ${fineOpacity(value)})`
  const tooltip = isCoarse
    ? `Токен ${value} (макро)`
    : `Токен ${value} (микро, прозрачность ${fineOpacity(value).toFixed(2)})`

  return (
    <div
      className="token-cell"
      style={{
        width: size,
        height: size,
        background: bg,
        border: isCoarse ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(99,102,241,0.2)',
        animation: `token-appear 0.3s ease ${index * 0.015}s both`
      }}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      {showTooltip && (
        <div className="token-tooltip">{tooltip}</div>
      )}
    </div>
  )
}

export default function TokenizerVisual({ analysis }) {
  const coarseTokens = Array.isArray(analysis?.coarse_tokens) ? analysis.coarse_tokens : []
  const fineTokens   = Array.isArray(analysis?.fine_tokens)   ? analysis.fine_tokens   : []

  if (coarseTokens.length === 0) return null

  const totalTokens  = coarseTokens.length + fineTokens.length
  const uniqueTokens = new Set([...coarseTokens, ...fineTokens]).size
  const entropy      = estimateEntropy(coarseTokens)

  return (
    <div className="glass-card" style={{ padding: '20px 24px', animation: 'slideInUp 0.4s ease' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
        <h2 className="section-title">Карта токенизации</h2>
        <div style={{ display: 'flex', gap: '8px' }}>
          <span className="badge badge-indigo">Всего: {totalTokens}</span>
          <span className="badge badge-muted">Уник: {uniqueTokens}</span>
          <span className="badge badge-cyan">H={entropy}</span>
        </div>
      </div>

      {/* Coarse tokens */}
      <div style={{ marginBottom: '12px' }}>
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Макротокены (Тренд) ({coarseTokens.length})
        </div>
        <div className="token-grid">
          {coarseTokens.map((v, i) => (
            <TokenCell key={i} value={v} size="24px" isCoarse index={i} />
          ))}
        </div>
      </div>

      {/* Fine tokens */}
      {fineTokens.length > 0 && (
        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Микротокены (Волатильность) ({fineTokens.length})
          </div>
          <div className="token-grid">
            {fineTokens.map((v, i) => (
              <TokenCell key={i} value={v} size="16px" isCoarse={false} index={i} />
            ))}
          </div>
        </div>
      )}

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginTop: '4px' }}>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Низкая волатильность</span>
        <div style={{ display: 'flex', gap: '3px', alignItems: 'center', flex: 1 }}>
          {[0, 8, 16, 24].map(v => (
            <div
              key={v}
              style={{
                flex: 1,
                height: '8px',
                background: tokenColor(v),
                borderRadius: '2px'
              }}
            />
          ))}
        </div>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Высокая волатильность</span>
      </div>

      {/* Stats row */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: '12px',
        marginTop: '16px',
        paddingTop: '16px',
        borderTop: '1px solid var(--glass-border)'
      }}>
        {[
          { label: 'Всего токенов', value: totalTokens },
          { label: 'Уникальных токенов', value: uniqueTokens },
          { label: 'Энтропия Шеннона', value: `${entropy} бит` }
        ].map(({ label, value }) => (
          <div key={label} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '18px', fontWeight: '700', color: 'var(--accent-cyan)' }}>{value}</div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>{label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
